import sqlite3
import pandas as pd
import numpy as np
import xgboost as xgb
from sklearn.model_selection import train_test_split
from sklearn.metrics import log_loss, roc_auc_score
from onnxmltools.convert.common.data_types import FloatTensorType
import joblib
from onnxmltools import convert_xgboost

def extract_features(db_path):
    conn = sqlite3.connect(db_path)
    
    query = """
    SELECT 
        match_id,
        game_time,
        nw_diff,
        score_diff,
        radiant_win
    FROM stratz_history
    ORDER BY match_id, game_time
    """
    
    print("Extracting data from DB...")
    df = pd.read_sql_query(query, conn)
    conn.close()
    
    if df.empty:
        print("No data found!")
        return pd.DataFrame(), pd.Series(), []
        
    print(f"Extracted {len(df)} rows.")
    
    # Calculate rolling features
    # Since Stratz data is exactly 1 minute apart (game_time = 0, 60, 120...)
    # 60s change is just diff(1)
    df['nw_change_60s'] = df.groupby('match_id')['nw_diff'].diff(1).fillna(0)
    df['score_change_60s'] = df.groupby('match_id')['score_diff'].diff(1).fillna(0)
    
    df = df.dropna()
    
    features = ['game_time', 'nw_diff', 'score_diff', 'nw_change_60s', 'score_change_60s']
    
    X = df[features]
    y = df['radiant_win']
    
    return X, y, features

def train_and_export():
    db_path = './data/dota_poly_collection.sqlite'
    X, y, feature_names = extract_features(db_path)
    
    if X.empty:
        print("Dataset is empty. Cannot train. Generating dummy model.")
        X = pd.DataFrame(np.random.rand(100, 5), columns=['game_time', 'nw_diff', 'score_diff', 'nw_change_60s', 'score_change_60s'])
        y = np.random.randint(0, 2, 100)
    
    X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42)
    
    print("Training XGBoost Classifier...")
    model = xgb.XGBClassifier(n_estimators=100, max_depth=4, learning_rate=0.1, objective='binary:logistic')
    model.fit(X_train.values, y_train)
    
    preds = model.predict_proba(X_test.values)[:, 1]
    auc = roc_auc_score(y_test, preds)
    loss = log_loss(y_test, preds)
    print(f"Model AUC: {auc:.4f} | Log Loss: {loss:.4f}")
    
    # Save standard joblib model
    model_path_joblib = 'dota_xgboost.joblib'
    joblib.dump(model, model_path_joblib)
    print(f"Saved standard model to {model_path_joblib}")
    
    # Convert to ONNX
    print("Converting to ONNX format...")
    # For XGBClassifier, the output is probability, but onnx conversion needs to know it's a float input
    initial_type = [('float_input', FloatTensorType([None, X.shape[1]]))]
    
    onnx_model = convert_xgboost(
        model, 
        initial_types=initial_type,
        target_opset=12
    )
    
    model_path_onnx = './research/dota_xgboost.onnx'
    with open(model_path_onnx, "wb") as f:
        f.write(onnx_model.SerializeToString())
    print(f"Saved ONNX model to {model_path_onnx}")

if __name__ == "__main__":
    train_and_export()
