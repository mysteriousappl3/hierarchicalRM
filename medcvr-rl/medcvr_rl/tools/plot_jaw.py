#!/usr/bin/env python3
import pandas as pd
import numpy as np
import seaborn as sns
from scipy.signal import savgol_filter

import matplotlib.pyplot as plt
import matplotlib as mpl


def main():
  print('Graphing')

  data = pd.read_csv('jaw_tests/0.csv')
  t = np.arange(0.0, (len(data['efforts'])*1/30), 1/30)
  data['time'] = t
  data[["efforts"]] = data[["efforts"]].apply(savgol_filter,  window_length=20, polyorder=2)
  data[["positions"]] = data[["positions"]].apply(savgol_filter,  window_length=30, polyorder=2)

  sns.set_theme()
  sns.set_style("whitegrid")
  sns.despine()
  fig, ax1 = plt.subplots(figsize=(9, 5))
  palette = sns.color_palette('muted', 5)

  sns.lineplot(x='time', y='efforts', data=data, color=palette[1], ax=ax1, linewidth=1.5)
  ax1.set_ylabel('Torque (Nm)', fontsize=20, labelpad=10, color='#333333')
  ax1.tick_params(axis='y', labelcolor=palette[1], labelsize=14)
  ax1.set_xlabel('Time (s)', fontsize=20, color='#333333')
  ax1.tick_params(axis='x', labelsize=14)

  ax2 = ax1.twinx()

  sns.lineplot(x='time', y='positions', data=data, color=palette[0], ax=ax2, linewidth=1.5)

  ax2.set_ylabel('Commanded Jaw Angle (rad)', fontsize=20, labelpad=10, color=palette[0])
  ax2.tick_params(axis='y', labelcolor=palette[0], labelsize=14)
  
  ax2.grid(False)


  # plot the "effort" data on the second y-axis


  # fig.suptitle('Effort Throghout Cut During Jaw Close/Open', fontsize=26)

  plt.close(1)
  # display the plot
  # plt.show()
  # save the plot as a file instead of displaying it
  fig.tight_layout()
  plt.savefig('cut0.png', dpi=300)

  # show a message indicating the plot has been saved
  print('Plot saved as myplot.png')


if __name__ == '__main__':
  main()
