#!/usr/bin/env python

import matplotlib.pyplot as plt
import seaborn as sns
import numpy as np


def main():
    data = [
        0.351681071973871,
        0.257040277007036,
        0.243247284030076,
        0.125769036007114,
        0.119744593044743,
        0.0672377449809574,
        0.0108244669390842,
    ][::-1]
    labels = [
        "Starting the Target-Emulator container",
        "Removing the Target-Emulator container",
        "Starting and waiting for the Target-Emulator",
        "Process the OID filename mapping",
        "OpenVAS scan",
        "Terminating the Target-Emulator",
        "Other",
    ][::-1]

    fig, ax = plt.subplots(figsize=(12, 6), subplot_kw=dict(aspect="equal"))

    # define Seaborn color palette to use
    colors = sns.color_palette("rocket", len(data))  # [0 : len(data)]

    # Based on: https://matplotlib.org/stable/gallery/pie_and_polar_charts/pie_and_donut_labels.html
    # create pie chart
    wedges, texts, autotexts = ax.pie(
        data,
        # labels=labels,
        colors=colors,
        autopct="%.0f%%",
        textprops={"fontsize": 18},
        startangle=90,
        counterclock=True,
        # labeldistance=1.05,
        wedgeprops=dict(width=0.5),
        radius=1,
    )
    for autotext in autotexts:
        autotext.set_color("white")

    bbox_props = dict(boxstyle="square,pad=0.3", fc="w", ec="k", lw=1.72)
    kw = dict(arrowprops=dict(arrowstyle="-"), bbox=bbox_props, zorder=0, va="center")

    for i, p in enumerate(wedges):
        if i == 1:
            divisor = 1.05
        else:
            divisor = 2
        ang = (p.theta2 - p.theta1) / divisor + p.theta1
        y = np.sin(np.deg2rad(ang))
        x = np.cos(np.deg2rad(ang))
        if i == 0:
            horizontalalignment = "right"
            y_factor = 1.2
        else:
            horizontalalignment = {-1: "right", 1: "left"}[int(np.sign(x))]
            y_factor = 1.1
        connectionstyle = f"angle,angleA=0,angleB={ang}"
        kw["arrowprops"].update({"connectionstyle": connectionstyle})
        ax.annotate(
            labels[i],
            xy=(x, y),
            xytext=(1.2 * np.sign(x), y_factor * y),
            horizontalalignment=horizontalalignment,
            fontsize=30,
            **kw,
        )

    # ax.set_title("Aufteilung der Laufzeit für einen Test-Case", pad=-10.0, fontsize=35)

    plt.show()


if __name__ == "__main__":
    main()
