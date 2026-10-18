% MATLAB tiledlayout teaching examples. Author: SKILL应用测试
% Run: tiledlayout_demo  (MATLAB R2025b; base MATLAB only)
% Deterministic analytical signals, no random data or external files.
clear; close all; clc;
root = fileparts(mfilename('fullpath'));
out = fullfile(root,'figures'); if ~exist(out,'dir'), mkdir(out); end
diary(fullfile(root,'matlab-run.log'));
fprintf('MATLAB %s | %s\n',version,datetime('now'));
set(groot,'defaultFigureVisible','off','defaultAxesFontName','Arial', ...
    'defaultAxesFontSize',28,'defaultTextFontSize',28, ...
    'defaultLineLineWidth',2.5,'defaultAxesColorOrder',[44 62 112;183 62 62]/255);
x = linspace(0,2*pi,200);
y = sin(x); z = cos(x);

%% 1. Fixed grid: layout first, axes second, plotting third.
f=figure('Color','w','Position',[50 50 1100 620]);
t=tiledlayout(f,2,2,'TileSpacing','compact','Padding','compact');
nexttile(t); plot(x,y); title('(a) sin(x)');
nexttile(t); plot(x,z); title('(b) cos(x)');
nexttile(t); plot(x,y.^2); title('(c) sin^2(x)');
nexttile(t); plot(x,y.*z); title('(d) sin(x)cos(x)');
saveplot(f,t,out,'01_grid');

%% 2. Axes handle and a second curve in the same tile.
f=figure('Color','w','Position',[50 50 1100 620]);
t=tiledlayout(f,1,2,'TileSpacing','compact','Padding','compact');
ax1=nexttile(t,1); plot(ax1,x,y); title(ax1,'(a) sin(x)');
ax2=nexttile(t,2); plot(ax2,x,z); hold(ax2,'on');
plot(ax2,x,0.5*z,'--'); title(ax2,'(b) cos(x)');
ylim(ax1,[-1.2 1.2]); ylim(ax2,[-1.2 1.2]);
saveplot(f,t,out,'02_handles');

%% 3. Span [rows columns], starting at tile 1.
f=figure('Color','w','Position',[50 50 1100 620]);
t=tiledlayout(f,2,2,'TileSpacing','compact','Padding','compact');
nexttile(t,1,[1 2]); plot(x,[y;z]); title('(a) Two signals');
nexttile(t,3); scatter(y,z,22,x,'filled'); title('(b) Phase');
nexttile(t,4); histogram(y,8); title('(c) Distribution');
saveplot(f,t,out,'03_span');

%% 4. Shared labels and linked x limits.
f=figure('Color','w','Position',[50 50 1100 620]);
t=tiledlayout(f,2,1,'TileSpacing','compact','Padding','compact');
ax1=nexttile(t); plot(ax1,x,y); title('(a) sin(x)');
ax2=nexttile(t); plot(ax2,x,z); title('(b) cos(x)');
linkaxes([ax1 ax2],'x'); xlim(ax1,[0 pi]);
xlabel(t,'x (rad)','FontSize',28); ylabel(t,'Amplitude','FontSize',28);
title(t,'Shared x range','FontSize',28);
saveplot(f,t,out,'04_shared');

%% 5. Export the entire layout rather than a single axes.
exportgraphics(t,fullfile(out,'whole_layout.png'),'Resolution',300);
exportgraphics(t,fullfile(out,'whole_layout.pdf'),'ContentType','vector');
fprintf('Completed: 4 examples, PNG + vector PDF + FIG; whole_layout exports.\n');
diary off;

function saveplot(f,t,out,name)
    drawnow;
    exportgraphics(t,fullfile(out,[name '.png']),'Resolution',180);
    exportgraphics(t,fullfile(out,[name '.pdf']),'ContentType','vector');
    savefig(f,fullfile(out,[name '.fig']));
    fprintf('Saved %s | axes=%d\n',name,numel(findall(f,'Type','axes')));
end



