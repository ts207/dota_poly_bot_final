import pandas as pd
import numpy as np

try:
    df = pd.read_csv('data/shadow_signals.csv')
    if df.empty:
        print("Shadow log is empty.")
    else:
        print(f"Summary of {len(df)} logged signals:")
        print("-" * 30)
        print("Action distribution:")
        print(df['action'].value_counts())
        print("\nTrigger distribution (FIRE only):")
        fire_df = df[df['action'] == 'FIRE']
        if not fire_df.empty:
            print(fire_df['trigger'].value_counts())
            print("\nAverage Edge by Trigger (FIRE only):")
            print(fire_df.groupby('trigger')['edge'].mean())
        else:
            print("No FIRE actions logged.")
except Exception as e:
    print(f"Error: {e}")
