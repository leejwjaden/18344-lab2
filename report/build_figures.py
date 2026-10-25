"""Regenerate report figures/tables from committed measurements; no benchmarks run.
Requires matplotlib. Run from any directory: python report/build_figures.py.
"""
import csv
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
deps = ROOT / 'lab2-output/report-deps'
if deps.exists():
    sys.path.insert(0, str(deps))
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np

SESSION = ROOT / 'results/task4/session-3973386ea9622d3cee1b'
FIG = HERE / 'figures'
GEN = HERE / 'generated'
FIG.mkdir(exist_ok=True)
GEN.mkdir(exist_ok=True)

def read(path):
    with path.open(newline='') as f:
        return list(csv.DictReader(f))

rows = read(SESSION / 'part4/measurements.csv')
designs = read(SESSION / 'part4/design_space.csv')
hw = read(SESSION / 'part4/hardware.csv')
best = json.loads((SESSION / 'part4/recommended.json').read_text())
hardware = {(int(r['size_kb']), int(r['block_bytes']), int(r['ways'])): r for r in hw}
ids = {r['config_id']: i + 1 for i, r in enumerate(designs)}
front = sorted([r for r in designs if r['pareto_optimal'] == 'True'], key=lambda r: float(r['amat_ns']))
assert len(designs) == 20 and len(rows) == 40 and len(front) == 6
plt.rcParams.update({'font.family': 'DejaVu Sans', 'font.size': 9, 'axes.spines.top': False,
                     'axes.spines.right': False, 'pdf.fonttype': 42, 'axes.titleweight': 'bold'})
colors = ['#176a91', '#d57526', '#43805d', '#9256a0']

def save(fig, name):
    fig.savefig(FIG / (name + '.pdf'), bbox_inches='tight')
    fig.savefig(FIG / (name + '.png'), dpi=160, bbox_inches='tight')
    plt.close(fig)

def style(ax):
    ax.grid(axis='y', alpha=.22)
    ax.set_axisbelow(True)

CORRECTED = ROOT / 'results/task1-3-corrected/session-1a552b2c84d04b334d9e'
assert (CORRECTED / 'COMPLETE.json').exists()
derived = read(CORRECTED / 'part1/measurements.csv')
policy_rows = read(CORRECTED / 'part2/measurements.csv')
assert len(derived) == 36 and len(policy_rows) == 24
for field, ylabel, name in [('amat_ns', 'Single-level AMAT (ns)', 'task1-amat'),
                            ('l1_miss_rate', 'L1 miss rate (%)', 'task1-misses')]:
    fig, axes = plt.subplots(1, 2, figsize=(7, 2.8), layout='constrained')
    for ax, bench in zip(axes, ('gcc','leela')):
        for i,kb in enumerate((2,4,8)):
            for block in (32,64):
                rr=sorted([r for r in derived if r['benchmark']==bench and int(r['l1_kb'])==kb and int(r['l1_block'])==block], key=lambda r:int(r['l1_ways']))
                ax.plot([int(r['l1_ways']) for r in rr], [float(r[field])*(100 if field=='l1_miss_rate' else 1) for r in rr], marker='o', linestyle='--' if block==32 else '-', color=colors[i], label=f'{kb} KiB, {block} B')
        ax.set(title=bench, xlabel='L1 associativity (ways)', ylabel=ylabel, xticks=[1,2,4])
        style(ax)
    axes[1].legend(fontsize=6, ncol=2)
    save(fig,name)
policies=['random','lru','plru','round-robin']
fig, axes=plt.subplots(2,3,figsize=(7,4.5),layout='constrained')
for j,bench in enumerate(('gcc','leela')):
    for ax,(kb,ways) in zip(axes[j],[(2,1),(4,2),(8,4)]):
        rr=[next(r for r in policy_rows if r['benchmark']==bench and int(r['l1_kb'])==kb and r['l1_policy']==p) for p in policies]
        ax.bar(['Random','LRU','Bit-PLRU','RR'],[100*float(r['l1_miss_rate']) for r in rr],color=colors)
        ax.set(title=f'{bench}: {kb} KiB, {ways}-way',ylabel='Miss rate (%)')
        ax.tick_params(axis='x',labelsize=7);style(ax)
save(fig,'task2-corrected')

fig, axes=plt.subplots(1,2,figsize=(7,3.1),layout='constrained')
for ax,field,xlabel in zip(axes,['area_mm2','total_power_estimate_mw'],['Total area (mm²)','Estimated total power (mW)']):
    ax.scatter([float(r[field]) for r in designs],[float(r['amat_ns']) for r in designs],color='#aab4bc',s=23,label='All 20 designs')
    ff=[r for r in designs if not any(float(q['amat_ns'])<=float(r['amat_ns']) and float(q[field])<=float(r[field]) and (float(q['amat_ns'])<float(r['amat_ns']) or float(q[field])<float(r[field])) for q in designs)]
    ff.sort(key=lambda r:float(r[field]))
    ax.plot([float(r[field]) for r in ff],[float(r['amat_ns']) for r in ff],'-o',color=colors[0],markersize=4,label='2D frontier')
    for r in front:
        ax.annotate(str(ids[r['config_id']]),(float(r[field]),float(r['amat_ns'])),xytext=(4,4),textcoords='offset points',fontsize=7)
    ax.set(xlabel=xlabel,ylabel='Mean AMAT (ns)');style(ax)
axes[0].legend(fontsize=7);save(fig,'task4-pareto')
fig, ax=plt.subplots(figsize=(7,2.9),layout='constrained')
for j,bench in enumerate(('gcc','leela')):
    yy=[float(next(r['amat_ns'] for r in rows if r['benchmark']==bench and r['config_id']==d['config_id'])) for d in front]
    ax.bar(np.arange(len(front))+(j-.5)*.36,yy,width=.36,label=bench,color=colors[j])
ax.set(xticks=range(len(front)),xticklabels=[f'D{ids[r["config_id"]]:02}' for r in front],ylabel='AMAT (ns)',xlabel='Three-objective Pareto designs (Table 3)')
ax.legend();style(ax);save(fig,'task4-bars')
fig,axes=plt.subplots(1,2,figsize=(7,2.8),layout='constrained')
for ax,stage,field,label in zip(axes,['sensitivity_associativity','sensitivity_size'],['l2_ways','l2_kb'],['L2 associativity (ways)','L2 capacity (KiB)']):
    for i,bench in enumerate(('gcc','leela')):
        rr=sorted([r for r in rows if r['benchmark']==bench and stage in r['stages'].split(';')],key=lambda r:int(r[field]))
        xx=[int(r[field]) for r in rr]
        ax.plot(xx,[float(r['amat_ns']) for r in rr],'-o',color=colors[i],label=bench)
        ax.set_xscale('log',base=2);ax.set_xticks(xx,[str(x) for x in xx])
    ax.set(xlabel=label,ylabel='AMAT (ns)');style(ax)
axes[0].legend();save(fig,'task4-sensitivity')

def esc(x):
    return str(x).replace('_',r'\_').replace('%',r'\%')
def table(name,header,data,cols):
    text=r'\begin{tabular}{'+cols+r'}\toprule'+'\n'+ ' & '.join(header)+r' \\ \midrule'+'\n'
    text+='\n'.join(' & '.join(map(str,row))+r' \\' for row in data)
    text+='\n'+r'\bottomrule\end{tabular}'+'\n'
    (GEN/(name+'.tex')).write_text(text.replace('\\toprule\\n','\\toprule\n'))
def cfg(s):
    return s.replace('K-','/').replace('B-','/').replace('way-','/').replace('round-robin','RR').replace('random','R').replace('plru','P').replace('lru','L')
table('designs',['ID','L1: C/B/A/P','L2: C/B/A/P','AMAT','Area','Power'],[
 [f'D{i+1:02}',cfg(r['l1']),cfg(r['l2']),f"{float(r['amat_ns']):.4f}",f"{float(r['area_mm2']):.3f}",f"{float(r['total_power_estimate_mw']):.2f}"] for i,r in enumerate(designs)],'rllrrr')
table('pareto',['ID','AMAT (ns)','Area (mm$^2$)','Power (mW)'],[
 [f'D{ids[r["config_id"]]:02}',f"{float(r['amat_ns']):.4f}",f"{float(r['area_mm2']):.3f}",f"{float(r['total_power_estimate_mw']):.2f}"] for r in front],'lrrr')
winner=[r for r in rows if r['config_id']==best['config_id']]
table('winner',['Benchmark',r'L1 miss (\%)',r'L2 local miss (\%)',r'DRAM / L1 (\%)','AMAT (ns)'],[
 [r['benchmark'],f"{100*float(r['l1_miss_rate']):.3f}",f"{100*float(r['l2_miss_rate']):.3f}",f"{100*int(r['dram_accesses'])/int(r['accesses']):.3f}",f"{float(r['amat_ns']):.4f}"] for r in winner],'lrrrr')
table('hardware',['Metric','L1','L2'],[[label,*[f'{float(hardware[tuple(best[k][:3])][field]):.5g}' for k in ['l1_config','l2_config']]] for label,field in [
 ('Read-hit latency (ns)','hit_ns'),('Miss latency (ns)','miss_ns'),('Write latency (ns)','write_ns'),('Read-hit energy (nJ)','hit_nj'),('Write energy (nJ)','write_nj'),('Leakage (mW)','leakage_mw'),('Area (mm$^2$)','area_mm2'),('Tag-array area (mm$^2$)','tag_area_mm2')]],'lrr')
summary={'task1':[{k:r[k] for k in ['benchmark','l1','l1_miss_rate','amat_ns']} for r in derived],
         'winner':winner,'policy':policy_rows}
(GEN/'analysis.json').write_text(json.dumps(summary,indent=2))
print('Generated six vector figures and four tables from validated measurements.')
