---
name: ml-forex-model-optimizer
description: Guidelines and routines for time-series Machine Learning models (XGBoost, GRU, Keras) in quantitative trading, focusing on scaling and weight optimization.
---

# Time-Series ML Model Optimizer Skill

This skill provides guidelines and templates to avoid feature scaling errors and weight mismatches when training and validating quantitative trading models (XGBoost, GRU).

## 1. Tree-based Model Feature Scaling Rules (XGBoost)

**Rule**: Do not apply standard scaling (`StandardScaler` or `MinMaxScaler`) to features when training XGBoost or Random Forest models unless specifically required by clustering methods. Trees split based on ordinal value boundaries, making feature scaling redundant and introducing "Scaler Class Mismatches" when predicting on live, unscaled MT5 data.

```python
# Train pipeline without scaling
import xgboost as xgb

def train_xgb_model(X_train, y_train, params):
    # Train directly on unscaled features
    dtrain = xgb.DMatrix(X_train, label=y_train)
    model = xgb.train(params, dtrain, num_boost_round=100)
    return model
```

## 2. Dynamic `scale_pos_weight` for Class Imbalance

**Warning**: Only apply positive class weighting (`scale_pos_weight`) when the target positive class (e.g. Trend UP) is the *minority* class. If positive is the *majority* class, setting a raw weight divisor (e.g. `raw_spw < 0.5`) will collapse model accuracy to near-zero as it penalises positive predictions.

```python
def calculate_scale_pos_weight(y):
    neg_count = sum(y == 0)
    pos_count = sum(y == 1)
    
    # Positive is minority class
    if pos_count > 0 and (neg_count / pos_count) > 2.0:
        return neg_count / pos_count
        
    # Positive is majority or balanced, do not penalize class 1
    return 1.0
```

## 3. GRU/LSTM Neural Network Sequence Scaling

For Keras neural networks (GRU, LSTM), sequence data *must* be scaled. Save the fitted scaler alongside the model binaries.

```python
import joblib
from sklearn.preprocessing import StandardScaler

def fit_and_save_scaler(X_train, scaler_path):
    scaler = StandardScaler()
    X_scaled = scaler.fit_transform(X_train)
    joblib.dump(scaler, scaler_path)
    return X_scaled, scaler

def predict_neural_network(model, X_raw, scaler_path):
    # Load original scaler to transform live features identically
    scaler = joblib.load(scaler_path)
    X_scaled = scaler.transform(X_raw)
    return model.predict(X_scaled)
```
