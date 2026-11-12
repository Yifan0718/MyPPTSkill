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
 if (nfft or len(x))%2:a[-1]*=2
 return np.fft.rfftfreq(nfft or len(x),1/fs),a

