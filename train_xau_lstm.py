#!/usr/bin/env python3
"""
LSTM trainer for XAU/USD (Gold) time-series forecasting.

Example:
  python train_xau_lstm.py \
      --data XAU_15m_data.csv \
      --datetime_col Date \
      --target Close \
      --seq_len 96 \
      --epochs 30 \
      --batch_size 64 \
      --resample 15min \
      --forecast_steps 16
"""

import argparse
import pickle
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import torch
import torch.nn as nn
from sklearn.preprocessing import MinMaxScaler
from torch.utils.data import DataLoader, Dataset


# ── CLI ──────────────────────────────────────────────────────────────────────

def parse_args():
    p = argparse.ArgumentParser(
        description="Train an LSTM model on XAU/USD (or any OHLCV) time-series CSV.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    # Data
    p.add_argument("--data",         required=True,          help="Path to input CSV file")
    p.add_argument("--datetime_col", default="Date",         help="Datetime column name")
    p.add_argument("--target",       default="Close",        help="Column to forecast")
    p.add_argument("--resample",     default="",             help="Resample frequency, e.g. '15min'")
    # Sequence
    p.add_argument("--seq_len",        type=int, default=96, help="Look-back window (bars)")
    p.add_argument("--forecast_steps", type=int, default=16, help="Steps ahead to predict")
    # Training
    p.add_argument("--epochs",     type=int,   default=30,   help="Max training epochs")
    p.add_argument("--batch_size", type=int,   default=64,   help="Mini-batch size")
    p.add_argument("--lr",         type=float, default=1e-3, help="Learning rate")
    p.add_argument("--patience",   type=int,   default=7,    help="Early-stopping patience")
    p.add_argument("--val_split",  type=float, default=0.1,  help="Validation fraction")
    p.add_argument("--test_split", type=float, default=0.1,  help="Test fraction")
    # Model
    p.add_argument("--hidden_size", type=int,   default=128, help="LSTM hidden units")
    p.add_argument("--num_layers",  type=int,   default=2,   help="LSTM stacked layers")
    p.add_argument("--dropout",     type=float, default=0.2, help="Dropout rate")
    # Misc
    p.add_argument("--out_dir", default="output", help="Directory for model/plots/metrics")
    p.add_argument("--seed",    type=int, default=42, help="Random seed")
    return p.parse_args()


# ── Data ─────────────────────────────────────────────────────────────────────

def load_data(args) -> pd.DataFrame:
    print(f"[data] Loading {args.data} …")
    df = pd.read_csv(args.data)

    if args.datetime_col not in df.columns:
        raise SystemExit(
            f"[error] Datetime column '{args.datetime_col}' not found.\n"
            f"        Available columns: {list(df.columns)}"
        )

    df[args.datetime_col] = pd.to_datetime(df[args.datetime_col], infer_datetime_format=True)
    df = df.set_index(args.datetime_col).sort_index()
    df = df.select_dtypes(include=[np.number])

    if args.target not in df.columns:
        raise SystemExit(
            f"[error] Target column '{args.target}' not found.\n"
            f"        Numeric columns: {list(df.columns)}"
        )

    if args.resample:
        agg = {}
        for col in df.columns:
            cl = col.lower()
            if cl == "open":   agg[col] = "first"
            elif cl == "high": agg[col] = "max"
            elif cl == "low":  agg[col] = "min"
            elif cl in ("volume", "vol"): agg[col] = "sum"
            else:              agg[col] = "last"
        df = df.resample(args.resample).agg(agg)
        print(f"[data] Resampled to {args.resample}: {len(df)} bars")

    df = df.dropna()
    print(f"[data] Shape: {df.shape}  |  {df.index[0]} → {df.index[-1]}")
    return df


def make_sequences(data: np.ndarray, target_idx: int, seq_len: int, horizon: int):
    X, y = [], []
    for i in range(len(data) - seq_len - horizon + 1):
        X.append(data[i : i + seq_len])
        y.append(data[i + seq_len : i + seq_len + horizon, target_idx])
    return np.array(X, dtype=np.float32), np.array(y, dtype=np.float32)


class TimeSeriesDataset(Dataset):
    def __init__(self, X, y):
        self.X = torch.from_numpy(X)
        self.y = torch.from_numpy(y)

    def __len__(self):
        return len(self.X)

    def __getitem__(self, idx):
        return self.X[idx], self.y[idx]


# ── Model ─────────────────────────────────────────────────────────────────────

class LSTMForecaster(nn.Module):
    """Stacked LSTM → FC head for multi-step forecasting."""

    def __init__(self, n_features: int, hidden_size: int, num_layers: int,
                 forecast_steps: int, dropout: float):
        super().__init__()
        self.lstm = nn.LSTM(
            input_size=n_features,
            hidden_size=hidden_size,
            num_layers=num_layers,
            batch_first=True,
            dropout=dropout if num_layers > 1 else 0.0,
        )
        self.head = nn.Sequential(
            nn.Dropout(dropout),
            nn.Linear(hidden_size, hidden_size // 2),
            nn.ReLU(),
            nn.Linear(hidden_size // 2, forecast_steps),
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        out, _ = self.lstm(x)       # (B, T, H)
        return self.head(out[:, -1])  # last step → (B, forecast_steps)


# ── Training ──────────────────────────────────────────────────────────────────

def run_epoch(model, loader, criterion, optimizer, device, train: bool):
    model.train(train)
    total_loss = 0.0
    with torch.set_grad_enabled(train):
        for xb, yb in loader:
            xb, yb = xb.to(device), yb.to(device)
            pred = model(xb)
            loss = criterion(pred, yb)
            if train:
                optimizer.zero_grad()
                loss.backward()
                nn.utils.clip_grad_norm_(model.parameters(), 1.0)
                optimizer.step()
            total_loss += loss.item() * len(xb)
    return total_loss / len(loader.dataset)


def train_model(model, train_loader, val_loader, args, device, out_dir: Path):
    optimizer = torch.optim.Adam(model.parameters(), lr=args.lr)
    scheduler = torch.optim.lr_scheduler.ReduceLROnPlateau(
        optimizer, patience=3, factor=0.5, verbose=True
    )
    criterion = nn.MSELoss()
    best_val   = float("inf")
    patience   = 0
    history    = {"train": [], "val": []}
    ckpt_path  = out_dir / "best_model.pt"

    print(f"\n{'Epoch':>6}  {'Train Loss':>12}  {'Val Loss':>12}  {'LR':>10}")
    print("─" * 50)

    for epoch in range(1, args.epochs + 1):
        tr = run_epoch(model, train_loader, criterion, optimizer, device, train=True)
        va = run_epoch(model, val_loader,   criterion, optimizer, device, train=False)
        scheduler.step(va)

        history["train"].append(tr)
        history["val"].append(va)
        lr = optimizer.param_groups[0]["lr"]
        print(f"{epoch:6d}  {tr:12.6f}  {va:12.6f}  {lr:10.2e}")

        if va < best_val:
            best_val = va
            patience = 0
            torch.save(model.state_dict(), ckpt_path)
        else:
            patience += 1
            if patience >= args.patience:
                print(f"\n[train] Early stop at epoch {epoch}  (best val={best_val:.6f})")
                break

    print(f"[train] Best val MSE: {best_val:.6f}  → {ckpt_path}")
    return history, ckpt_path


# ── Evaluation ────────────────────────────────────────────────────────────────

def inverse_target(arr_1d: np.ndarray, scaler: MinMaxScaler,
                   target_idx: int, n_features: int) -> np.ndarray:
    dummy = np.zeros((len(arr_1d), n_features))
    dummy[:, target_idx] = arr_1d
    return scaler.inverse_transform(dummy)[:, target_idx]


def evaluate_model(model, test_loader, scaler, target_idx: int,
                   n_features: int, forecast_steps: int, out_dir: Path, device):
    model.eval()
    preds, trues = [], []
    with torch.no_grad():
        for xb, yb in test_loader:
            preds.append(model(xb.to(device)).cpu().numpy())
            trues.append(yb.numpy())

    pred = np.concatenate(preds)   # (N, forecast_steps)
    true = np.concatenate(trues)   # (N, forecast_steps)

    pred_inv = np.stack([inverse_target(pred[:, s], scaler, target_idx, n_features)
                         for s in range(forecast_steps)], axis=1)
    true_inv = np.stack([inverse_target(true[:, s], scaler, target_idx, n_features)
                         for s in range(forecast_steps)], axis=1)

    mae  = np.mean(np.abs(pred_inv - true_inv))
    rmse = np.sqrt(np.mean((pred_inv - true_inv) ** 2))
    mape = np.mean(np.abs((true_inv - pred_inv) / np.where(true_inv == 0, 1e-8, true_inv))) * 100

    print(f"\n{'─'*50}")
    print(f"[eval] Test  MAE={mae:.4f}  RMSE={rmse:.4f}  MAPE={mape:.2f}%")

    metrics_txt = f"MAE:  {mae:.6f}\nRMSE: {rmse:.6f}\nMAPE: {mape:.4f}%\n"
    (out_dir / "metrics.txt").write_text(metrics_txt)
    print(metrics_txt.strip())

    # Per-step RMSE
    per_step = [np.sqrt(np.mean((pred_inv[:, s] - true_inv[:, s]) ** 2))
                for s in range(forecast_steps)]
    print("[eval] Per-step RMSE:")
    for s, v in enumerate(per_step, 1):
        print(f"       step {s:2d}: {v:.4f}")

    # Plot 1: actual vs predicted (step+1)
    n_show = min(300, len(true_inv))
    fig, ax = plt.subplots(figsize=(14, 5))
    ax.plot(true_inv[:n_show, 0], label="Actual",           linewidth=1.0)
    ax.plot(pred_inv[:n_show, 0], label="Predicted (t+1)",  linewidth=1.0, linestyle="--")
    ax.set_title("XAU/USD — Test: Actual vs Predicted (step t+1)")
    ax.set_xlabel("Sample"); ax.set_ylabel("Price (USD)")
    ax.legend(); fig.tight_layout()
    fig.savefig(out_dir / "forecast_step1.png", dpi=150)
    plt.close(fig)

    # Plot 2: per-step RMSE
    fig, ax = plt.subplots(figsize=(8, 4))
    ax.bar(range(1, forecast_steps + 1), per_step, color="steelblue")
    ax.set_title("Per-step RMSE on Test Set")
    ax.set_xlabel("Forecast step"); ax.set_ylabel("RMSE")
    fig.tight_layout()
    fig.savefig(out_dir / "per_step_rmse.png", dpi=150)
    plt.close(fig)

    return mae, rmse, mape


def plot_loss(history: dict, out_dir: Path):
    fig, ax = plt.subplots(figsize=(8, 4))
    ax.plot(history["train"], label="Train")
    ax.plot(history["val"],   label="Validation")
    ax.set_title("Training Loss (MSE)"); ax.set_xlabel("Epoch"); ax.set_ylabel("Loss")
    ax.legend(); fig.tight_layout()
    fig.savefig(out_dir / "loss_curve.png", dpi=150)
    plt.close(fig)


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    args = parse_args()

    torch.manual_seed(args.seed)
    np.random.seed(args.seed)

    device  = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"[info] Device  : {device}")
    print(f"[info] Out dir : {out_dir.resolve()}")

    # ── Load & scale ──────────────────────────────────────────────────────────
    df         = load_data(args)
    feat_cols  = list(df.columns)
    target_idx = feat_cols.index(args.target)
    n_features = len(feat_cols)
    print(f"[data] Features ({n_features}): {feat_cols}")
    print(f"[data] Target  : '{args.target}' (index {target_idx})")

    scaler = MinMaxScaler(feature_range=(0, 1))
    scaled = scaler.fit_transform(df.values).astype(np.float32)
    with open(out_dir / "scaler.pkl", "wb") as f:
        pickle.dump(scaler, f)

    # ── Sequences ─────────────────────────────────────────────────────────────
    X, y = make_sequences(scaled, target_idx, args.seq_len, args.forecast_steps)
    print(f"[data] X={X.shape}  y={y.shape}")

    n       = len(X)
    n_test  = max(1, int(n * args.test_split))
    n_val   = max(1, int(n * args.val_split))
    n_train = n - n_val - n_test

    if n_train <= 0:
        raise SystemExit(
            f"[error] Not enough samples ({n}) for the given splits. "
            "Reduce seq_len/forecast_steps or use more data."
        )

    X_tr, y_tr = X[:n_train],              y[:n_train]
    X_va, y_va = X[n_train:n_train+n_val], y[n_train:n_train+n_val]
    X_te, y_te = X[n_train+n_val:],        y[n_train+n_val:]
    print(f"[data] Split  train={len(X_tr)}  val={len(X_va)}  test={len(X_te)}")

    train_loader = DataLoader(TimeSeriesDataset(X_tr, y_tr), batch_size=args.batch_size,
                              shuffle=True, drop_last=True)
    val_loader   = DataLoader(TimeSeriesDataset(X_va, y_va), batch_size=args.batch_size)
    test_loader  = DataLoader(TimeSeriesDataset(X_te, y_te), batch_size=args.batch_size)

    # ── Model ─────────────────────────────────────────────────────────────────
    model = LSTMForecaster(
        n_features     = n_features,
        hidden_size    = args.hidden_size,
        num_layers     = args.num_layers,
        forecast_steps = args.forecast_steps,
        dropout        = args.dropout,
    ).to(device)

    n_params = sum(p.numel() for p in model.parameters() if p.requires_grad)
    print(f"\n[model] {model.__class__.__name__}  params={n_params:,}")
    print(model)

    # ── Train ─────────────────────────────────────────────────────────────────
    history, ckpt = train_model(model, train_loader, val_loader, args, device, out_dir)

    # ── Evaluate ──────────────────────────────────────────────────────────────
    model.load_state_dict(torch.load(ckpt, map_location=device))
    evaluate_model(model, test_loader, scaler, target_idx, n_features,
                   args.forecast_steps, out_dir, device)
    plot_loss(history, out_dir)

    print(f"\n{'─'*50}")
    print(f"[done] All outputs in: {out_dir.resolve()}/")
    for f in sorted(out_dir.iterdir()):
        print(f"       {f.name}")


if __name__ == "__main__":
    main()
