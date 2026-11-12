from pathlib import Path
import sqlite3,json,time,statistics,platform
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
R=Path(__file__).resolve().parents[1];D=R/'data';G=R/'figures';D.mkdir(exist_ok=True);G.mkdir(exist_ok=True)
N=200000;rng=np.random.default_rng(20261112)
tenants=rng.integers(1,101,N);amounts=rng.integers(100,100000,N);status=np.where(rng.random(N)<.1,'open','closed')
rows=[(i+1,int(tenants[i]),i,int(amounts[i]),str(status[i]),'x'*64) for i in range(N)]
schema='CREATE TABLE orders(id INTEGER PRIMARY KEY, tenant_id INTEGER, created_seq INTEGER, amount_cents INTEGER, status TEXT, payload TEXT)'
ddl={'Scan':None,'Tenant':'CREATE INDEX idx ON orders(tenant_id)','Composite':'CREATE INDEX idx ON orders(tenant_id,created_seq)','Covering':'CREATE INDEX idx ON orders(tenant_id,created_seq,amount_cents)'}
Q='SELECT created_seq, amount_cents FROM orders WHERE tenant_id=42 ORDER BY created_seq DESC LIMIT 20'
def connect(index=None):
 c=sqlite3.connect(':memory:');c.execute('PRAGMA page_size=4096');c.execute(schema);c.executemany('INSERT INTO orders VALUES(?,?,?,?,?,?)',rows);c.commit()
 if index:c.execute(index);c.commit()
 c.execute('ANALYZE');return c
def vm(c,sql,params=()):
 ticks=0
 def count():
  nonlocal ticks;ticks+=1;return 0
 c.set_progress_handler(count,1)
 try:result=c.execute(sql,params).fetchall()
 finally:c.set_progress_handler(None,0)
 return ticks,result
def measure(c,sql,params=()):
 count,result=vm(c,sql,params);times=[]
 for _ in range(3):c.execute(sql,params).fetchall()
 for _ in range(11):
  start=time.perf_counter_ns();c.execute(sql,params).fetchall();times.append((time.perf_counter_ns()-start)/1e6)
 return {'vm_instructions':count,'rows_returned':len(result),'median_ms':statistics.median(times),'times_ms':times,'plan':[r[3] for r in c.execute('EXPLAIN QUERY PLAN '+sql,params)],'result':result}
results={'N':N,'seed':20261112,'sqlite_version':sqlite3.sqlite_version,'python':platform.python_version(),'query':Q,'cases':{},'tenant42_rows':int(sum(tenants==42)),'open_rows':int(sum(status=='open'))}
conns={}
for name,index in ddl.items():
 c=connect(index);conns[name]=c;results['cases'][name]=measure(c,Q)
 results['cases'][name]['page_bytes']=c.execute('PRAGMA page_count').fetchone()[0]*4096
assert all(v['result']==results['cases']['Scan']['result'] for v in results['cases'].values())
# The same tenant/range query, with index order forced to expose the physical access path.
range_sql='SELECT sum(amount_cents) FROM orders INDEXED BY idx WHERE tenant_id=42 AND created_seq BETWEEN 80000 AND 119999'
reversed_conn=connect('CREATE INDEX idx ON orders(created_seq,tenant_id)')
results['range']={'query':range_sql,'tenant_first':measure(conns['Composite'],range_sql),'range_first':measure(reversed_conn,range_sql)}
assert results['range']['tenant_first']['result']==results['range']['range_first']['result']
# Coverage depends on selected columns.
payload_sql='SELECT created_seq, amount_cents, payload FROM orders WHERE tenant_id=42 ORDER BY created_seq DESC LIMIT 20'
results['payload']=measure(conns['Covering'],payload_sql)
# A partial covering index for an active subset.
partial=connect("CREATE INDEX idx ON orders(tenant_id,created_seq,amount_cents) WHERE status='open'")
full_active=connect('CREATE INDEX idx ON orders(status,tenant_id,created_seq,amount_cents)')
active_sql="SELECT created_seq,amount_cents FROM orders WHERE status='open' AND tenant_id=42 ORDER BY created_seq DESC LIMIT 20"
results['partial']={'query':active_sql,'partial':measure(partial,active_sql),'full':measure(full_active,active_sql)}
for label,c in [('partial',partial),('full',full_active)]:
 results['partial'][label]['index_bytes']=c.execute("SELECT sum(pgsize) FROM dbstat WHERE name='idx'").fetchone()[0]
assert results['partial']['partial']['result']==results['partial']['full']['result']
# Index maintenance: one transaction, 5000 identical inserted rows per alternative.
insert_rows=[(N+i+1,42,N+i,5000,'open','x'*64) for i in range(5000)]
for name,c in conns.items():
 before=c.total_changes;ticks=0
 def count():
  global ticks;ticks+=1;return 0
 c.execute('BEGIN');c.set_progress_handler(count,1);c.executemany('INSERT INTO orders VALUES(?,?,?,?,?,?)',insert_rows);c.set_progress_handler(None,0);c.rollback()
 results['cases'][name]['insert_vm_instructions']=ticks;assert c.total_changes-before==5000
# Page-level tree structure for the covering index.
results['tree']=[{'page_type':a,'pages':b,'cells':c,'bytes':d} for a,b,c,d in conns['Covering'].execute("SELECT pagetype,count(*),sum(ncell),sum(pgsize) FROM dbstat WHERE name='idx' GROUP BY pagetype")]
results['depth']=conns['Covering'].execute("SELECT max(length(path)-length(replace(path,'/',''))-1) FROM dbstat WHERE name='idx'").fetchone()[0]
# Range selectivity with a non-covering index vs table scan; fetch payload to force row lookups.
sel=connect('CREATE INDEX idx ON orders(created_seq)');selectivity=[]
for fraction in [.001,.01,.1,.5,1.]:
 hi=int(N*fraction)-1
 a,_=vm(sel,'SELECT sum(length(payload)) FROM orders INDEXED BY idx WHERE created_seq<=?',(hi,));b,_=vm(sel,'SELECT sum(length(payload)) FROM orders NOT INDEXED WHERE created_seq<=?',(hi,))
 selectivity.append({'fraction':fraction,'indexed_vm':a,'scan_vm':b})
results['selectivity']=selectivity
# Function predicates vs an indexable equality.
expr=connect('CREATE INDEX idx ON orders(tenant_id)')
results['predicate']={'direct':measure(expr,'SELECT count(*) FROM orders WHERE tenant_id=42'),'expression':measure(expr,'SELECT count(*) FROM orders WHERE tenant_id+0=42')}
assert results['predicate']['direct']['result']==results['predicate']['expression']['result']
BLUE='#2F5597';TEAL='#168578';ORANGE='#E47C27';GRAY='#8292A6'
plt.rcParams.update({'font.family':'DejaVu Sans','font.size':14,'axes.labelsize':15,'axes.titlesize':16,'xtick.labelsize':13,'ytick.labelsize':13,'legend.fontsize':12,'axes.spines.top':False,'axes.spines.right':False,'axes.edgecolor':'#BAC3CD','pdf.fonttype':42,'axes.labelcolor':'#263443','text.color':'#263443'})
def finish(fig,name):fig.tight_layout(pad=.8);fig.savefig(G/(name+'.png'),dpi=220,facecolor='white');fig.savefig(G/(name+'.pdf'),facecolor='white');plt.close(fig)
names=list(ddl);v=[results['cases'][n]['vm_instructions'] for n in names]
fig,ax=plt.subplots(figsize=(10.6,3.3));ax.barh(names,v,color=[GRAY,ORANGE,BLUE,TEAL]);ax.set_xscale('log');ax.set_xlabel('Executed SQLite virtual-machine instructions (log scale)');ax.invert_yaxis();ax.grid(axis='x',alpha=.2);ax.set_axisbelow(True)
for i,value in enumerate(v):ax.text(value*1.16,i,f'{value:,}',va='center',fontsize=14)
ax.set_xlim(10,max(v)*4);finish(fig,'read_work')
fig,axs=plt.subplots(1,2,figsize=(10.6,3.3));axs[0].bar(names,[results['cases'][n]['median_ms'] for n in names],color=[GRAY,ORANGE,BLUE,TEAL]);axs[0].set_yscale('log');axs[0].set_ylabel('Median time / ms');axs[1].bar(names,[(results['cases'][n]['page_bytes']-results['cases']['Scan']['page_bytes'])/1048576 for n in names],color=[GRAY,ORANGE,BLUE,TEAL]);axs[1].set_ylabel('Added storage / MiB')
for ax in axs:ax.tick_params(axis='x',labelsize=11);ax.grid(axis='y',alpha=.2);ax.set_axisbelow(True)
finish(fig,'latency_storage')
fig,axs=plt.subplots(1,2,figsize=(10.6,3.3));axs[0].bar(names,[results['cases'][n]['insert_vm_instructions']/5000 for n in names],color=[GRAY,ORANGE,BLUE,TEAL]);axs[0].set_ylabel('VM steps per insert');axs[1].plot([100*x['fraction'] for x in selectivity],[x['indexed_vm']/1e6 for x in selectivity],'-o',color=BLUE,label='Non-covering index');axs[1].plot([100*x['fraction'] for x in selectivity],[x['scan_vm']/1e6 for x in selectivity],'-o',color=GRAY,label='Table scan');axs[1].set(xlabel='Rows selected / %',ylabel='VM steps / million');axs[1].legend(frameon=False,fontsize=11)
for ax in axs:ax.grid(alpha=.2);ax.set_axisbelow(True)
axs[0].tick_params(axis='x',labelsize=11);finish(fig,'costs')
fig,axs=plt.subplots(1,2,figsize=(10.6,3.3));axs[0].bar(['Tenant, sequence','Sequence, tenant'],[results['range'][k]['vm_instructions'] for k in ['tenant_first','range_first']],color=[TEAL,ORANGE]);axs[0].set_ylabel('VM instructions for range aggregate');axs[1].bar(['Partial active index','Full status index'],[results['partial'][k]['index_bytes']/1048576 for k in ['partial','full']],color=[TEAL,BLUE]);axs[1].set_ylabel('Index storage / MiB')
for ax in axs:ax.tick_params(axis='x',labelsize=11);ax.grid(axis='y',alpha=.2);ax.set_axisbelow(True)
finish(fig,'order_partial')
(D/'results.json').write_text(json.dumps(results,indent=2),encoding='utf8')
print(json.dumps({k:results[k] for k in ['N','sqlite_version','tenant42_rows','tree','depth']},indent=2));print([(n,v['vm_instructions'],round(v['median_ms'],4)) for n,v in results['cases'].items()])
for c in list(conns.values())+[reversed_conn,partial,full_active,sel,expr]:c.close()
