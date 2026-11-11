"""檢索範圍的時空立方體示意圖：地面是地圖，縱軸是時段。五格橫排對應五個題型（標題中文、其餘英文）；圖例另存一張。"""
import sys
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
from matplotlib.patches import Patch, Polygon

plt.rcParams["font.family"] = ["Helvetica Neue", "PingFang TC"]
plt.rcParams["mathtext.fontset"] = "stix"

GRAY, FRAME, GRID = "#9a9a9a", "#a8a8a8", "#e3e3e3"
ORANGE, BLUE = "#D55E00", "#0072B2"
EX, EY, H = np.array([1.0, 0.13]), np.array([-0.42, 0.34]), 0.98
SLOTS = ["morning", "noon", "afternoon", "evening"]


def P(x, y, t=0.0):
    x, y, t = np.asarray(x, float), np.asarray(y, float), np.asarray(t, float)
    return np.stack([x * EX[0] + y * EY[0], x * EX[1] + y * EY[1] + t * H], axis=-1)


def band(*names):
    i = [SLOTS.index(n) for n in names]
    return min(i) / 4, (max(i) + 1) / 4


def circle(cx, cy, r, n=120):
    a = np.linspace(0, 2 * np.pi, n, endpoint=False)
    return cx + r * np.cos(a), cy + r * np.sin(a)


def blob(cx, cy, r, n=160, seed=(0.16, 2, 0.6, 0.10, 3, 2.1)):
    a = np.linspace(0, 2 * np.pi, n, endpoint=False)
    a1, k1, p1, a2, k2, p2 = seed
    rr = r * (1 + a1 * np.cos(k1 * a + p1) + a2 * np.cos(k2 * a + p2))
    return cx + rr * np.cos(a), cy + rr * np.sin(a)


def frame(ax, title, asked, widened=()):
    # 地面與格線
    ax.add_patch(Polygon(P([0, 1, 1, 0], [0, 0, 1, 1]), closed=True, fc="white", ec="none", zorder=0))
    for v in np.linspace(0.2, 0.8, 4):
        ax.plot(*P([v, v], [0, 1]).T, color=GRID, lw=0.8, zorder=0.1)
        ax.plot(*P([0, 1], [v, v]).T, color=GRID, lw=0.8, zorder=0.1)
    # 後牆與頂邊
    for seg in ([(0, 1, 0), (1, 1, 0)], [(1, 1, 0), (1, 0, 0)], [(1, 1, 0), (1, 1, 1)], [(1, 0, 0), (1, 0, 1)],
                [(0, 1, 1), (1, 1, 1)], [(1, 1, 1), (1, 0, 1)]):
        q = P(*zip(*seg))
        ax.plot(q[:, 0], q[:, 1], color=FRAME, lw=1.0, zorder=0.2)
    # 座標軸
    arrow = dict(arrowstyle="-|>", color="black", lw=1.2, shrinkA=0, shrinkB=0, mutation_scale=11)
    o, xe, ye = P(0, 0)[()], P(1.07, 0)[()], P(0, 1.04)[()]
    t0, t1 = P(0, 1, 0)[()], P(0, 1, 1.09)[()]
    for a, b in ((o, xe), (o, ye), (t0, t1)):
        ax.annotate("", xy=b, xytext=a, arrowprops=arrow, zorder=5)
    ax.text(xe[0] + 0.03, xe[1], "$x$", fontsize=15, va="center")
    ax.text(ye[0] - 0.045, ye[1] - 0.035, "$y$", fontsize=15, ha="center", va="center")
    ax.text(t1[0] - 0.025, t1[1] + 0.01, "$t$", fontsize=15, ha="center")
    # 時段刻度
    for i, name in enumerate(SLOTS):
        lo, hi = P(0, 1, i / 4)[()], P(0, 1, (i + 1) / 4)[()]
        ax.plot([lo[0] - 0.012, lo[0]], [lo[1], lo[1]], color="black", lw=0.8, zorder=5)
        on, near = name in asked, name in widened
        if on or near:
            ax.plot([lo[0], hi[0]], [lo[1] + 0.012, hi[1] - 0.012], color=BLUE, lw=5.5 if on else 3,
                    alpha=1 if on else 0.45, solid_capstyle="butt", zorder=6)
        ax.text(lo[0] - 0.035, (lo[1] + hi[1]) / 2, name, fontsize=13, ha="right", va="center",
                color=BLUE if (on or near) else GRAY, fontweight="bold" if on else "normal")
    ax.text(-0.80, 1.55, title, fontsize=21, fontweight="bold", ha="left", va="bottom")


def slab(ax, t0, t1, alpha=0.10, ls=(0, (3, 2))):
    for t in (t0, t1):
        ax.add_patch(Polygon(P([0, 1, 1, 0], [0, 0, 1, 1], t), closed=True, fc=BLUE, alpha=alpha, ec="none", zorder=1))
        ax.add_patch(Polygon(P([0, 1, 1, 0], [0, 0, 1, 1], t), closed=True, fc="none", ec=BLUE, lw=0.9, ls=ls,
                             zorder=1.1))


def column(ax, curve, t0, t1, fill=None, alpha=0.25, lw=1.0, ls=(0, (3, 2)), z=2.0, foot=False):
    """以 curve 為底的直立柱。fill 是 None 時只畫虛線外框（條件），否則畫實心（查詢範圍）。"""
    x, y = curve
    bot, top = P(x, y, t0), P(x, y, t1)
    i, j = int(np.argmin(bot[:, 0])), int(np.argmax(bot[:, 0]))
    if fill:
        lo, hi = min(i, j), max(i, j)
        # 柱身：左右輪廓線之間、靠前的那半圈
        front = list(range(lo, hi + 1))
        back = list(range(hi, len(x))) + list(range(0, lo + 1))
        near = front if bot[front, 1].mean() < bot[back, 1].mean() else back
        body = np.vstack([bot[near], top[near][::-1]])
        ax.add_patch(Polygon(body, closed=True, fc=fill, alpha=alpha, ec="none", zorder=z))
        ax.add_patch(Polygon(top, closed=True, fc=fill, alpha=alpha + 0.12, ec=BLUE, lw=lw, zorder=z + 0.2))
        ax.plot(*np.vstack([bot[near]]).T, color=BLUE, lw=lw, zorder=z + 0.2)
        far = back if near is front else front
        ax.plot(*bot[far].T, color=BLUE, lw=0.7, ls=(0, (2, 2)), zorder=z + 0.1)
        for k in (i, j):
            ax.plot([bot[k, 0], top[k, 0]], [bot[k, 1], top[k, 1]], color=BLUE, lw=lw, zorder=z + 0.2)
    else:
        for ring in (bot, top):
            ax.add_patch(Polygon(ring, closed=True, fc=BLUE, alpha=0.04, ec="none", zorder=z))
            ax.add_patch(Polygon(ring, closed=True, fc="none", ec=BLUE, lw=lw, ls=ls, zorder=z + 0.1))
        for k in (i, j):
            ax.plot([bot[k, 0], top[k, 0]], [bot[k, 1], top[k, 1]], color=BLUE, lw=lw, ls=ls, zorder=z + 0.1)
    if foot:
        ax.add_patch(Polygon(P(x, y, 0), closed=True, fc="none", ec=BLUE, lw=0.8, ls=(0, (1.5, 1.5)), zorder=0.5))


def place(ax, x, y, name=None, dx=-0.035, dy=-0.03):
    q = P(x, y)[()]
    ax.plot(*q, "o", color="black", ms=4, zorder=4)
    if name:
        ax.text(q[0] + dx, q[1] + dy, f"${name}$", fontsize=14, ha="center", va="center", zorder=4)


def frag(ax, x, y, t, hit, z=7):
    q, g = P(x, y, t)[()], P(x, y)[()]
    ax.plot([g[0], q[0]], [g[1], q[1]], color=GRAY, lw=0.7, ls=(0, (1, 2)), zorder=z - 3.5)
    if hit:
        ax.plot(*q, "o", color=ORANGE, ms=8.5, mec="white", mew=0.8, zorder=z)
    else:
        ax.plot(*q, "o", color="white", ms=7, mec=GRAY, mew=1.4, zorder=z)


def unknown(ax, x, y, hit=True, z=6.5):
    """時段不明的片段：任何時段都相符，畫成貫穿整個時間軸的直線。"""
    a, b = P(x, y, 0.02)[()], P(x, y, 0.98)[()]
    ax.plot([a[0], b[0]], [a[1], b[1]], color=ORANGE if hit else GRAY, lw=2.6, solid_capstyle="round", zorder=z)




def note(ax, x, y, t, s, dx=0.0, dy=0.0, ha="left"):
    q = P(x, y, t)[()]
    ax.text(q[0] + dx, q[1] + dy, s, fontsize=13, color=BLUE, ha=ha, va="center", zorder=9,
            bbox=dict(fc="white", ec="none", alpha=0.8, pad=1.2))


fig, axes = plt.subplots(1, 5, figsize=(26, 5.6))
fig.subplots_adjust(left=0.01, right=0.99, top=0.99, bottom=0.01, wspace=0.0)
axes = axes.ravel()
for ax in axes:
    ax.set_xlim(-0.84, 1.20)
    ax.set_ylim(-0.08, 1.72)
    ax.set_aspect("equal")
    ax.axis("off")

PM = band("afternoon")
G = (0.50, 0.46)

# (a) 停留經驗
ax = axes[0]
frame(ax, "停留經驗", {"afternoon"})
slab(ax, *PM)
column(ax, circle(*G, 0.10), 0, 1, foot=True)
column(ax, circle(*G, 0.10), *PM, fill=BLUE, z=3)
place(ax, *G, "G", dx=-0.02, dy=-0.04)
place(ax, 0.84, 0.74)
frag(ax, G[0] - 0.035, G[1], 0.11, False)
frag(ax, G[0] - 0.035, G[1], 0.63, True)
unknown(ax, G[0] + 0.045, G[1] + 0.01)
frag(ax, 0.84, 0.74, 0.62, False)
frag(ax, 0.84, 0.74, 0.90, False)

# (b) 移動經驗：地點是交通節點，地面畫出經過它的路線
ax = axes[1]
frame(ax, "移動經驗", {"afternoon"})
S = (0.52, 0.50)
route = P([0.08, 0.30, S[0], 0.74, 0.95], [0.16, 0.40, S[1], 0.56, 0.86])
ax.plot(route[:, 0], route[:, 1], color="#666666", lw=1.6, zorder=0.6)
ax.annotate("", xy=route[-1], xytext=route[-2], zorder=0.6,
            arrowprops=dict(arrowstyle="-|>", color="#666666", lw=1.6, mutation_scale=12, shrinkA=0, shrinkB=0))
slab(ax, *PM)
column(ax, circle(*S, 0.10), 0, 1, foot=True)
column(ax, circle(*S, 0.10), *PM, fill=BLUE, z=3)
place(ax, *S, "S", dx=-0.02, dy=-0.045)
place(ax, 0.30, 0.40)
frag(ax, S[0], S[1], 0.60, True)
frag(ax, S[0] + 0.03, S[1] + 0.02, 0.69, True)
frag(ax, S[0], S[1], 0.30, False)
frag(ax, 0.30, 0.40, 0.62, False)
r = P(0.95, 0.86)[()]
ax.text(r[0] - 0.03, r[1] + 0.05, "route", fontsize=13, color="#666666", ha="center")

# (c) 找地點
ax = axes[2]
frame(ax, "找地點", {"afternoon"})
area = blob(0.50, 0.50, 0.30)
slab(ax, *PM)
column(ax, area, 0, 1, foot=True)
column(ax, area, *PM, fill=BLUE, alpha=0.16, z=2.8)
pts = (((0.36, 0.40), "A"), ((0.62, 0.62), "B"), ((0.60, 0.33), "C"))
for (x, y), n in pts:
    column(ax, circle(x, y, 0.055), *PM, fill=BLUE, alpha=0.22, lw=0.9, z=3.2)
    place(ax, x, y, n, dx=-0.035, dy=-0.03)
place(ax, 0.92, 0.90)
frag(ax, 0.36, 0.40, 0.61, True)
frag(ax, 0.62, 0.62, 0.68, True)
frag(ax, 0.60, 0.33, 0.58, True)
frag(ax, 0.62, 0.62, 0.92, False)
frag(ax, 0.60, 0.33, 0.14, False)
frag(ax, 0.92, 0.90, 0.60, False)

# (d) 找時間：不限時段，依時段分組
ax = axes[3]
frame(ax, "找時間", (), set(SLOTS))
column(ax, circle(*G, 0.10), 0, 1, foot=True, lw=0.01)
for i in range(4):
    column(ax, circle(*G, 0.10), i / 4, (i + 1) / 4, fill=BLUE, alpha=0.14 + 0.07 * (i % 2), z=3 + i * 0.3)
place(ax, *G, "G", dx=-0.02, dy=-0.04)
place(ax, 0.84, 0.74)
for dx, t in ((-0.03, 0.10), (0.03, 0.17), (0.0, 0.40), (-0.03, 0.60), (0.035, 0.70), (0.0, 0.90)):
    frag(ax, G[0] + dx, G[1], t, True)
frag(ax, 0.84, 0.74, 0.35, False)
frag(ax, 0.84, 0.74, 0.80, False)

# (e) 比較：兩個子查詢，分開取回
ax = axes[4]
frame(ax, "比較", {"afternoon"})
G1, G2 = (0.30, 0.42), (0.72, 0.58)
slab(ax, *PM)
for g, n, lab in ((G1, "G_1", "sub-query 1"), (G2, "G_2", "sub-query 2")):
    column(ax, circle(*g, 0.10), 0, 1, foot=True)
    column(ax, circle(*g, 0.10), *PM, fill=BLUE, z=3)
    place(ax, *g, n, dx=-0.03, dy=-0.045)
    note(ax, g[0], g[1], 1.0, lab, dx=0.0, dy=0.10, ha="center")
frag(ax, G1[0], G1[1], 0.62, True)
frag(ax, G1[0], G1[1], 0.12, False)
frag(ax, G2[0] - 0.03, G2[1], 0.58, True)
frag(ax, G2[0] + 0.03, G2[1], 0.69, True)
frag(ax, G2[0], G2[1], 0.88, False)

out = sys.argv[1]
fig.savefig(out + ".png", dpi=200, facecolor="white", bbox_inches="tight", pad_inches=0.08)
fig.savefig(out + ".pdf", facecolor="white", bbox_inches="tight", pad_inches=0.08)

# 圖例：另存一張橫條
handles = [
    Line2D([], [], marker="o", ls="none", color=ORANGE, mec="white", ms=11, label="Fragment, retrieved"),
    Line2D([], [], marker="o", ls="none", color="white", mec=GRAY, mew=1.4, ms=9, label="Fragment, not retrieved"),
    Line2D([], [], color=ORANGE, lw=2.6, label="Fragment with unknown time slot"),
    Line2D([], [], color=GRAY, lw=0.9, ls=(0, (1, 2)), label="Projection onto the map"),
    Patch(fc="none", ec=BLUE, ls=(0, (3, 2)), lw=1.0, label="Place scope / time condition"),
    Patch(fc=BLUE, alpha=0.35, ec=BLUE, lw=1.0, label="Retrieval range (intersection)"),
]
lf = plt.figure(figsize=(26, 0.6))
lf.legend(handles=handles, loc="center", ncol=6, frameon=False, fontsize=16, handlelength=2.4, columnspacing=2.6)
lf.savefig(out + "_legend.png", dpi=200, facecolor="white", bbox_inches="tight", pad_inches=0.08)
lf.savefig(out + "_legend.pdf", facecolor="white", bbox_inches="tight", pad_inches=0.08)
print("saved", out)
