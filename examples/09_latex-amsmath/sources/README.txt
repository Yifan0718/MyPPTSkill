amsmath 数学排版示例
作者：SKILL应用测试

main.tex 顺序载入五个片段，构成一份可复用、可交叉引用的完整 LaTeX 文档。
01-definition.tex：矩阵、向量、二次目标和非负约束。
02-align.tex：梯度与线性方程组的对齐、逐行编号及 notag。
03-split.tex：消去一个变量，将同一条长推导保持为一个编号。
04-cases.tex：分段最优解及解向量。
05-references.tex：用 eqref 引用前面的推导，验证 β=0 的具体结果。

在当前目录运行：
latexmk -norc -pdf -interaction=nonstopmode -halt-on-error -outdir=build main.tex

也可以连续运行两遍 pdflatex main.tex，让交叉引用解析完成。
文档依赖 article、geometry、amsmath，使用标准 Computer Modern 数学字体。

数学主线：
Q=[[2,1],[1,2]]，b=(3,β)，J(x)=xᵀQx/2−bᵀx，约束 x₂≥0。
Q 的特征值为1和3。令x₂=t后，x₁=(3−t)/2；
g(t)=3t²/4+(3/2−β)t−9/4。
t*=max(0,(2β−3)/3)，x*=((3−t*)/2,t*)。
当β=0，x*=(3/2,0)，最小值为−9/4。

资料：AMS / LaTeX Project，User’s Guide for the amsmath Package。
https://mirrors.ctan.org/macros/latex/required/amsmath/amsldoc.pdf
