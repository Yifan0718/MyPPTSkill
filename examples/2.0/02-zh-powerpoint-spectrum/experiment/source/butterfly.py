from plot_style import plt,finish,BLUE,RED,GRAY
fig,ax=plt.subplots(figsize=(6.0,3.55))
for stage in range(3):
 size=2**(stage+1)
 for base in range(0,8,size):
  for j in range(size//2):
   a,b=base+j,base+j+size//2
   for src,dst in [(a,a),(a,b),(b,a),(b,b)]:
    ax.plot([stage,stage+1],[7-src,7-dst],color=BLUE if src==dst else RED,alpha=.65,lw=1)
for st in range(4):ax.scatter([st]*8,range(8),s=13,color=BLUE,zorder=3)
for i,k in enumerate([0,4,2,6,1,5,3,7]):ax.text(-.1,7-i,f'x[{k}]',ha='right',va='center',fontsize=13)
for i in range(8):ax.text(3.1,7-i,f'X[{i}]',va='center',fontsize=13)
ax.set(xlim=(-.6,3.65),ylim=(-.6,7.65));ax.axis('off')
for st,label in enumerate(['Bit reverse','2-point','4-point','8-point']):ax.text(st,7.45,label,ha='center',fontsize=12)
finish(fig,'butterfly')

