import sqlite3
import pandas as pd
import numpy as np
import xgboost as xgb
from sklearn.model_selection import train_test_split
from onnxconverter_common.data_types import FloatTensorType
from skl2onnx import convert_sklearn
import joblib

def extract_features(db_path):
    conn = sqlite3.connect(db_path)
    
    # We will join dota_ticks and market_ticks (COMBINED_RADIANT) based on closest time
    query = """
    SELECT 
        d.ts_ms,
        d.match_key,
        d.game_time,
        d.nw_diff,
        d.nw_diff_pct,
        d.radiant_score - d.dire_score AS score_diff,
        m.mid,
        m.spread
    FROM dota_ticks d
    JOIN market_ticks m ON m.ts_ms = (
        SELECT ts_ms FROM market_ticks 
        WHERE token_id = 'COMBINED_RADIANT' 
          AND ts_ms >= d.ts_ms - 2000 
          AND ts_ms <= d.ts_ms + 2000
        ORDER BY ABS(ts_ms - d.ts_ms)
        LIMIT 1
    )
    WHERE m.token_id = 'COMBINED_RADIANT'
    ORDER BY d.ts_ms
    """
    
    print("Extracting data from DB...")
    df = pd.read_sql_query(query, conn)
    conn.close()
    
    if df.empty:
        print("No data found!")
        return pd.DataFrame()
        
    print(f"Extracted {len(df)} rows.")
    
    # Calculate rolling features
    df = df.sort_values(by=['match_key', 'ts_ms'])
    
    # 60s ago
    df['ts_60s_ago'] = df['ts_ms'] - 60000
    
    # Very crude approximation of 60s change using shift for demo purposes, 
    # a rigorous pipeline would use exact timestamp matching or rolling windows.
    # We will compute changes using simple diffs for the MVP pipeline.
    df['nw_change_60s'] = df.groupby('match_key')['nw_diff'].diff(periods=60).fillna(0)
    df['score_change_60s'] = df.groupby('match_key')['score_diff'].diff(periods=60).fillna(0)
    df['market_change_60s'] = df.groupby('match_key')['mid'].diff(periods=60).fillna(0)
    
    # Target: the final 'mid' price in the match, assuming it resolves to 1 or 0
    # or the 'mid' price 120s in the future as a proxy for "expected move".
    # Let's predict mid price 120s in the future.
    df['target_mid'] = df.groupby('match_key')['mid'].shift(-120)
    
    df = df.dropna()
    
    features = ['game_time', 'nw_diff', 'nw_diff_pct', 'score_diff', 'mid', 'spread', 
                'nw_change_60s', 'score_change_60s', 'market_change_60s']
    
    X = df[features]
    y = df['target_mid']
    
    return X, y, features

def train_and_export():
    db_path = '../data/dota_poly_collection.sqlite'
    X, y, feature_names = extract_features(db_path)
    
    if X.empty:
        print("Dataset is empty. Cannot train. Generating dummy model.")
        # Create dummy data so we can at least serialize a model
        X = pd.DataFrame(np.random.rand(100, 9), columns=['game_time', 'nw_diff', 'nw_diff_pct', 'score_diff', 'mid', 'spread', 'nw_change_60s', 'score_change_60s', 'market_change_60s'])
        y = np.random.rand(100)
    
    X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42)
    
    print("Training XGBoost model...")
    # We use XGBRegressor wrapped in scikit-learn API to make ONNX export easier
    model = xgb.XGBRegressor(n_estimators=100, max_depth=4, learning_rate=0.1, objective='reg:squarederror')
    model.fit(X_train, y_train)
    
    score = model.score(X_test, y_test)
    print(f"Model R^2 score: {score:.4f}")
    
    # Save standard joblib model
    model_path_joblib = 'dota_xgboost.joblib'
    joblib.dump(model, model_path_joblib)
    print(f"Saved standard model to {model_path_joblib}")
    
    # Convert to ONNX
    print("Converting to ONNX format...")
    initial_type = [('float_input', FloatTensorType([None, X.shape[1]]))]
    onnx_model = convert_sklearn(model, initial_types=initial_type)
    
    model_path_onnx = 'dota_xgboost.onnx'
    with open(model_path_onnx, "wb") as f:
        f.write(onnx_model.SerializeToString())
    print(f"Saved ONNX model to {model_path_onnx}")

if __name__ == "__main__":
    train_and_export()
