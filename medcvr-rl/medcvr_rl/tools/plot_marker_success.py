#!/usr/bin/env python3
import pandas as pd
import numpy as np
import seaborn as sns

import matplotlib.pyplot as plt
import matplotlib as mpl


def main():
  print('Graphing')

  data = pd.read_csv('data.csv')
  marker_widths = []
  succes_rates = []
  for markerwidth in np.arange(0.4, 1.2, 0.05):
    success = data.loc[(data['markerwidth'] - markerwidth < 0.01) & (data['result'] > 18)]
    success_rate = len(success)/5
    marker_widths.append(markerwidth)
    succes_rates.append(success_rate)

  print(marker_widths)
  print(succes_rates)
  
  data_2 = pd.DataFrame({'markerwidth': marker_widths, 'success_rate': succes_rates})

  sns.set_theme()
  sns.set_style("whitegrid")
  sns.despine()
  fig, ax1 = plt.subplots(figsize=(9, 5))
  palette = sns.color_palette('muted', 5)

  sns.lineplot(x='markerwidth', y='success_rate', data=data_2, color=palette[1], ax=ax1, linewidth=1.5)
  ax1.set_ylabel('Success Rate', fontsize=20, labelpad=10, color='#333333')
  ax1.tick_params(axis='y', labelcolor=palette[1], labelsize=14)
  ax1.set_xlabel('Marker Width', fontsize=20, color='#333333')
  ax1.tick_params(axis='x', labelsize=14)

  fig.suptitle('Success Rate vs Marker Size', fontsize=26)

  plt.close(1)
  # display the plot
  plt.show()
  # save the plot as a file instead of displaying it
  fig.tight_layout()
  plt.savefig('data.png', dpi=300)

  # show a message indicating the plot has been saved
  print('Plot saved as myplot.png')


def main2():
  print('Graphing')

  data = pd.read_csv('framerate.csv')
  print(data['Time'].mean())

  sns.set_theme()
  sns.set_style("whitegrid")
  sns.despine()
  fig, ax1 = plt.subplots(figsize=(9, 5))
  palette = sns.color_palette('muted', 5)

  sns.lineplot(x='Frame', y='Time', data=data, color=palette[1], ax=ax1, linewidth=1)
  ax1.set_ylabel('Delta Time Since Last Frame [s]', fontsize=20, labelpad=10, color='#333333')
  ax1.tick_params(axis='y', labelcolor=palette[1], labelsize=14)
  ax1.set_xlabel('Frame', fontsize=20, color='#333333')
  ax1.tick_params(axis='x', labelsize=14)

  ax2 = ax1.twinx()

  sns.lineplot(x='Frame', y='numcut', data=data, color=palette[0], ax=ax2, linewidth=1)

  ax2.set_ylabel('Number of Ropes Cut', fontsize=20, labelpad=10, color=palette[0])
  ax2.tick_params(axis='y', labelcolor=palette[0], labelsize=14)
  
  ax2.grid(False)

  # fig.suptitle('Success Rate vs Marker Size', fontsize=26)

  plt.close(1)
  # display the plot
  plt.show()
  # save the plot as a file instead of displaying it
  fig.tight_layout()
  plt.savefig('data.png', dpi=300)

  # show a message indicating the plot has been saved
  print('Plot saved as myplot.png')


if __name__ == '__main__':
  main2()
