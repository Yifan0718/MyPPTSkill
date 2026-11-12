from pathlib import Path
import json
import numpy as np
from scipy import signal
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
ROOT=Path(__file__).resolve().parents[1];FIG=ROOT/'figures';DATA=ROOT/'data'
FIG.mkdir(exist_ok=True);DATA.mkdir(exist_ok=True)
BLUE='#2C3E70';RED='#C55443';TEAL='#14867D';GRAY='#737D8C';ORANGE='#E88A26'
plt.rcParams.update({'font.family':'DejaVu Sans','font.size':14,'axes.labelsize':15,'axes.titlesize':15,
 'xtick.labelsize':13.5,'ytick.labelsize':13.5,'legend.fontsize':13,'axes.spines.top':False,
 'axes.spines.right':False,'axes.edgecolor':'#9FA9B6','axes.labelcolor':'#263449','text.color':'#263449',
 'xtick.color':'#526174','ytick.color':'#526174','axes.linewidth':.7,'lines.linewidth':1.5,'pdf.fonttype':42})
def finish(fig,name):
 has_legend=any(ax.get_legend() is not None for ax in fig.axes)
 for ax in fig.axes:
  if ax.get_legend() is not None:
   handles,labels=ax.get_legend_handles_labels()
   ax.get_legend().remove()
   ax.legend(handles,labels,loc='lower center',bbox_to_anchor=(.5,1.015),frameon=False,ncol=len(labels),fontsize=11,handlelength=1.5,columnspacing=1)
  if has_legend and ax.get_title():ax.set_title(ax.get_title(),y=1.23)
 fig.tight_layout(pad=.8,w_pad=1.7)
 fig.savefig(FIG/(name+'.png'),dpi=200,facecolor='white')
 fig.savefig(FIG/(name+'.pdf'),facecolor='white')
 plt.close(fig)
def grid(ax):ax.grid(alpha=.2,linewidth=.6);ax.set_axisbelow(True)
def amp(x,fs,window='hann',nfft=None):
 w=signal.get_window(window,len(x),fftbins=True);X=np.fft.rfft(x*w,n=nfft)
 a=np.abs(X)/w.sum();a[1:-1]*=2
 if (nfft or len(x))>1 and (nfft or len(x))%2:a[-1]*=2
 return np.fft.rfftfreq(nfft or len(x),1/fs),a
FS=2048;T=4;N=FS*T;t=np.arange(N)/FS;rng=np.random.default_rng(20261112)
steady=.9*np.sin(2*np.pi*120*t)+.35*np.sin(2*np.pi*123*t)+.15*np.sin(2*np.pi*420*t)
sweep=.28*signal.chirp(t,500,4,700)
burst=.7*np.exp(-.5*((t-2.6)/.04)**2)*np.sin(2*np.pi*900*t)
noise=.08*rng.normal(size=N);drift=.3+.05*t/T;x=steady+sweep+burst+noise+drift
np.savez(DATA/'signals.npz',t=t,x=x,steady=steady,sweep=sweep,burst=burst,noise=noise,drift=drift)
np.savetxt(DATA/'signal.csv',np.c_[t,x],delimiter=',',header='time_s,voltage_V',comments='')
results={'fs':FS,'duration_s':T,'N':N,'seed':20261112,'dtype':'float64'}

# 2: one signal, time detail and component envelopes
fig,axs=plt.subplots(1,2,figsize=(11.8,3.35))
axs[0].plot(t,x,color=BLUE,lw=.65);axs[0].set(xlabel='Time / s',ylabel='Voltage / V',xlim=(0,4),title='(a) Complete record')
q=t<.08;axs[1].plot(t[q],x[q],color=BLUE,label='Combined');axs[1].plot(t[q],steady[q],color=RED,alpha=.85,label='Stationary tones')
axs[1].set(xlabel='Time / s',ylabel='Voltage / V',title='(b) First 80 ms');axs[1].legend(frameon=False,ncol=2)
for ax in axs:grid(ax)
finish(fig,'signal')
# 4: alias equality at sample times
fs=2048;ts=np.arange(20)/fs;dense=np.linspace(0,ts[-1],1600)
fig,axs=plt.subplots(1,2,figsize=(11.8,3.35),gridspec_kw={'width_ratios':[1.45,1]})
axs[0].plot(dense*1000,np.cos(2*np.pi*1350*dense),color=RED,label='1350 Hz',lw=1)
axs[0].plot(dense*1000,np.cos(2*np.pi*698*dense),color=TEAL,label='698 Hz',lw=1)
axs[0].scatter(ts*1000,np.cos(2*np.pi*1350*ts),color=BLUE,s=18,zorder=5,label='Samples')
axs[0].set(xlabel='Time / ms',ylabel='Amplitude',title='(a) Same sampled values');axs[0].legend(frameon=False,ncol=3,fontsize=11)
freq=np.linspace(0,3072,400);fold=np.abs((freq+1024)%2048-1024)
axs[1].plot(freq,fold,color=BLUE);axs[1].plot(1350,698,'o',color=RED);axs[1].annotate('1350 → 698',(1350,698),xytext=(1550,800),fontsize=12)
axs[1].set(xlabel='Input frequency / Hz',ylabel='Observed frequency / Hz',title='(b) Frequency folding',xticks=[0,1024,2048,3072],yticks=[0,512,1024])
for ax in axs:grid(ax)
finish(fig,'aliasing');assert np.max(abs(np.cos(2*np.pi*1350*ts)-np.cos(2*np.pi*698*ts)))<1e-12
# 5: naive vs filtered downsampling
z=np.sin(2*np.pi*120*t)+.5*np.sin(2*np.pi*900*t);naive=z[::4];filtered=signal.resample_poly(z,1,4)
fig,axs=plt.subplots(1,2,figsize=(11.8,3.35))
for ax,xx,label,col in zip(axs,[naive,filtered],['(a) Keep every fourth sample','(b) Low-pass, then decimate'],[RED,TEAL]):
 f,a=amp(xx,512);ax.plot(f,a,color=col);ax.set(xlim=(110,135),ylim=(0,1.12),xlabel='Frequency / Hz',ylabel='Amplitude / V',title=label);grid(ax)
finish(fig,'resampling')
f,a=amp(naive,512);_,af=amp(filtered,512);results['downsample']={'naive_124':float(a[np.argmin(abs(f-124))]),'filtered_124':float(af[np.argmin(abs(f-124))]),'filtered_120':float(af[np.argmin(abs(f-120))])}
# 6: DFT coefficient correlation
n=np.arange(32);sig=np.cos(2*np.pi*5*n/32)
fig,axs=plt.subplots(1,2,figsize=(11.8,3.35))
axs[0].plot(n,sig,'o-',color=BLUE,ms=3,label='x[n], k=5');axs[0].plot(n,np.cos(2*np.pi*6*n/32),'--',color=RED,label='k=6 basis');axs[0].set(xlabel='Sample n',ylabel='Value',title='(a) Compare discrete basis waves');axs[0].legend(frameon=False,ncol=2,fontsize=12)
coef=np.abs(np.fft.rfft(sig));axs[1].stem(np.arange(len(coef)),coef,linefmt=BLUE,markerfmt='o',basefmt=' ');axs[1].set(xlabel='DFT bin k',ylabel='|X[k]|',xticks=[0,4,8,12,16],title='(b) Projection concentrates at k=5');grid(axs[1]);finish(fig,'dft')
# 8: physical record length resolves close tones
fig,axs=plt.subplots(1,3,figsize=(11.8,3.35),sharey=True)
for ax,duration in zip(axs,[.25,1,4]):
 tt=np.arange(int(FS*duration))/FS;zz=.9*np.sin(2*np.pi*120*tt)+.35*np.sin(2*np.pi*123*tt)
 f,a=amp(zz,FS,nfft=32768);ax.plot(f,a,color=BLUE);ax.axvline(120,color=GRAY,ls=':',lw=.7);ax.axvline(123,color=GRAY,ls=':',lw=.7)
 ax.set(xlim=(110,133),ylim=(0,1.1),xlabel='Frequency / Hz',title=f'T = {duration:g} s; 1/T = {1/duration:g} Hz');grid(ax)
axs[0].set_ylabel('Amplitude / V');finish(fig,'duration')
# 9 zero-padding samples same short-record spectrum
short=.9*np.sin(2*np.pi*120*t[:512])+.35*np.sin(2*np.pi*123*t[:512])
fig,axs=plt.subplots(1,2,figsize=(11.8,3.35))
f,a=amp(short,FS);fz,az=amp(short,FS,nfft=8192)
axs[0].plot(fz,az,color=BLUE,label='8192-point FFT');axs[0].plot(f,a,'o',color=RED,label='512-point FFT',ms=5)
axs[0].set(xlim=(112,132),xticks=[112,116,120,124,128,132],xlabel='Frequency / Hz',ylabel='Amplitude / V',title='(a) Same 0.25 s record');axs[0].legend(frameon=False,fontsize=12)
long=.9*np.sin(2*np.pi*120*t)+.35*np.sin(2*np.pi*123*t);f,a=amp(long,FS);axs[1].plot(f,a,color=TEAL);axs[1].set(xlim=(112,132),xticks=[112,116,120,124,128,132],xlabel='Frequency / Hz',ylabel='Amplitude / V',title='(b) Four seconds of observations')
for ax in axs:grid(ax)
finish(fig,'padding')
# 10 leakage
tt=np.arange(2048)/FS;fig,axs=plt.subplots(1,2,figsize=(11.8,3.35))
for ff,col in [(120,BLUE),(120.5,RED)]:
 zz=np.sin(2*np.pi*ff*tt);axs[0].plot(1000*np.r_[tt[-30:]-1,tt[:30]],np.r_[zz[-30:],zz[:30]],'o-',ms=2,color=col,label=f'{ff:g} Hz')
 f,a=amp(zz,FS,'boxcar');axs[1].plot(f,20*np.log10(np.maximum(a,1e-8)),color=col,label=f'{ff:g} Hz')
axs[0].set(xlabel='Time around seam / ms',xticks=[-10,0,10],ylabel='Value',title='(a) End joined to start');axs[1].set(xlabel='Frequency / Hz',ylabel='Amplitude / dB re 1 V',xlim=(90,150),ylim=(-100,3),title='(b) Rectangular-window spectrum')
for ax in axs:grid(ax);ax.legend(frameon=False,fontsize=12)
finish(fig,'leakage')
# 11 windows and numerical response metrics
fig,axs=plt.subplots(1,2,figsize=(11.8,3.35));wm=[]
for name,label,col,zero in [('boxcar','Rectangular',GRAY,1),('hann','Hann',BLUE,2),('blackmanharris','Blackman-Harris',RED,4)]:
 w=signal.get_window(name,256,fftbins=True);freq=np.fft.rfftfreq(65536)*256;resp=abs(np.fft.rfft(w,65536))/sum(w)
 axs[0].plot(np.arange(256)/256,w,color=col,label=label);axs[1].plot(freq,20*np.log10(np.maximum(resp,1e-8)),color=col,label=label)
 sidelobe=max(resp[freq>zero+.01]);wm.append({'name':label,'gain':float(w.mean()),'mainlobe_bins':2*zero,'sidelobe_db':float(20*np.log10(sidelobe)),'enbw_bins':float(256*(w@w)/(sum(w)**2))})
axs[0].set(xlabel='Normalized time n/N',ylabel='Weight',title='(a) Time-domain taper');axs[1].set(xlabel='Frequency offset / bins',ylabel='Normalized response / dB',xlim=(0,10),ylim=(-115,3),title='(b) Mainlobe and sidelobes')
for ax in axs:grid(ax)
axs[0].legend(frameon=False,fontsize=11);finish(fig,'windows');results['windows']=wm
# 12 coherent amplitude, exact-bin
coherent=.9*np.sin(2*np.pi*120*tt);rows=[]
for name in ['boxcar','hann','blackmanharris']:
 w=signal.get_window(name,len(tt));X=np.fft.rfft(coherent*w);rows.append({'window':name,'uncorrected':float(2*abs(X[120])/len(tt)),'corrected':float(2*abs(X[120])/sum(w))})
assert max(abs(r['corrected']-.9) for r in rows)<1e-12;results['amplitude']=rows
# 13 PSD Parseval
stationary=steady+noise;w=signal.get_window('hann',N);X=np.fft.rfft(stationary*w);psd=abs(X)**2/(FS*(w@w));psd[1:-1]*=2;f=np.fft.rfftfreq(N,1/FS)
integral=psd.sum()*FS/N;weighted=np.sum((stationary*w)**2)/(w@w);assert abs(integral-weighted)<1e-12
results['power']={'integral':float(integral),'weighted_mean_square':float(weighted),'rms':float(np.sqrt(integral))}
fig,axs=plt.subplots(1,2,figsize=(11.8,3.35));axs[0].semilogy(f,psd,color=BLUE,lw=1);axs[0].set(xlim=(0,1024),xlabel='Frequency / Hz',ylabel='PSD / V²/Hz',title='(a) Stationary signal PSD');axs[1].plot(f,np.cumsum(psd)*FS/N,color=TEAL);axs[1].set(xlim=(0,1024),xlabel='Upper frequency / Hz',ylabel='Integrated power / V²',title='(b) Integrated spectral power')
for ax in axs:grid(ax)
finish(fig,'power')
# 14 Welch variance on noise, with common frequency and 300 independent records
rr=np.random.default_rng(418);raw=[];avg=[]
for _ in range(300):
 xx=.08*rr.normal(size=N);f1,P1=signal.periodogram(xx,FS,window='hann',detrend=False);f2,P2=signal.welch(xx,FS,window='hann',nperseg=512,noverlap=256,detrend=False)
 raw.append(P1[np.argmin(abs(f1-800))]);avg.append(P2[np.argmin(abs(f2-800))])
target=2*.08**2/FS;raw=np.array(raw)/target;avg=np.array(avg)/target
results['welch']={'segments':31,'trials':300,'periodogram_cv':float(raw.std(ddof=1)/raw.mean()),'welch_cv':float(avg.std(ddof=1)/avg.mean())}
fig,axs=plt.subplots(1,2,figsize=(11.8,3.35));f1,P1=signal.periodogram(noise,FS,window='hann',detrend=False);f2,P2=signal.welch(noise,FS,window='hann',nperseg=512,noverlap=256,detrend=False)
axs[0].semilogy(f1,P1,color=GRAY,alpha=.65,lw=.7,label='Single periodogram');axs[0].semilogy(f2,P2,color=BLUE,lw=1.5,label='Welch');axs[0].axhline(target,color=TEAL,ls='--',label='Theory');axs[0].set(xlim=(0,1024),ylim=(1e-8,1e-4),xlabel='Frequency / Hz',ylabel='PSD / V²/Hz',title='(a) Same noise record');axs[0].legend(frameon=False,fontsize=11)
axs[1].hist(raw,bins=np.linspace(0,5,40),density=True,histtype='step',color=GRAY,label='Single periodogram');axs[1].hist(avg,bins=np.linspace(0,5,40),density=True,histtype='step',color=BLUE,label='Welch');axs[1].set(xlabel='Estimate / theoretical PSD',ylabel='Density',title='(b) 300 estimates at 800 Hz',xlim=(0,5));axs[1].legend(frameon=False,fontsize=11)
for ax in axs:grid(ax)
finish(fig,'welch')
# 15,16 STFT: direct sliding real FFT, exact frame centers
def stft(x,L,hop):
 windows=np.lib.stride_tricks.sliding_window_view(x,L)[::hop];win=signal.get_window('hann',L)
 a=abs(np.fft.rfft(windows*win,axis=1))/win.sum();a[:,1:-1]*=2
 if L>1 and L%2:a[:,-1]*=2
 return (np.arange(len(windows))*hop+L/2)/FS,np.fft.rfftfreq(L,1/FS),a.T
clean=signal.detrend(x)
times,freq,A=stft(clean,512,64)
fig,ax=plt.subplots(figsize=(11.8,3.35));im=ax.pcolormesh(times,freq,20*np.log10(np.maximum(A,1e-4)),shading='auto',cmap='magma',vmin=-55,vmax=0);ax.set(xlabel='Frame-center time / s',ylabel='Frequency / Hz',ylim=(0,1024),xlim=(0,4));fig.colorbar(im,ax=ax,label='Amplitude / dB re 1 V',pad=.015);finish(fig,'spectrogram')
fig,axs=plt.subplots(1,2,figsize=(11.8,3.35))
for ax,L,hop in zip(axs,[256,1024],[64,64]):
 times,freq,A=stft(clean,L,hop);im=ax.pcolormesh(times,freq,20*np.log10(np.maximum(A,1e-4)),shading='auto',cmap='magma',vmin=-55,vmax=0);ax.set(xlabel='Time / s',ylabel='Frequency / Hz',ylim=(450,1024),xlim=(1.8,3.4),xticks=[2.0,2.4,2.8,3.2],title=f'L={L}: {L/FS*1000:g} ms, {FS/L:g} Hz bins')
fig.colorbar(im,ax=axs,label='dB re 1 V',pad=.02,fraction=.025);fig.subplots_adjust(left=.07,right=.89,bottom=.22,top=.85,wspace=.28);fig.savefig(FIG/'stft-tradeoff.png',dpi=200,facecolor='white');fig.savefig(FIG/'stft-tradeoff.pdf');plt.close(fig)
# 17 diagnosis: stationary peaks and event envelopes
f,a=amp(clean,FS);mask=(f>=110)&(f<=135);peakids=signal.find_peaks(a[mask],prominence=.05)[0];peaks=f[mask][peakids]
sos=signal.butter(4,[850,950],btype='bandpass',fs=FS,output='sos');env=abs(signal.hilbert(signal.sosfiltfilt(sos,clean)));center=float(t[np.argmax(env)])
results['diagnosis']={'peaks_hz':peaks.tolist(),'burst_peak_s':center,'burst_envelope_V':float(env.max())}
fig,axs=plt.subplots(1,2,figsize=(11.8,3.35));axs[0].plot(f,a,color=BLUE);axs[0].set(xlim=(115,130),xlabel='Frequency / Hz',ylabel='Amplitude / V',title='(a) Four-second stationary spectrum');axs[1].plot(t,env,color=RED);axs[1].axvline(2.6,color=GRAY,ls='--');axs[1].set(xlim=(2.3,2.9),xlabel='Time / s',ylabel='850–950 Hz envelope / V',title='(b) Short-event localization')
for ax in axs:grid(ax)
finish(fig,'diagnosis')
results['checks']={'inverse_fft_error':float(np.max(abs(np.fft.irfft(np.fft.rfft(x),n=N)-x))), 'amplitude_error':max(abs(r['corrected']-.9) for r in rows),'parseval_error':float(abs(integral-weighted)),'alias_sample_error':float(np.max(abs(np.cos(2*np.pi*1350*ts)-np.cos(2*np.pi*698*ts))))}
(DATA/'results.json').write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding='utf8')
print(json.dumps(results,ensure_ascii=False,indent=2))



