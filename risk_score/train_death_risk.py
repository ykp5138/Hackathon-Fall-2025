import os
import joblib
import pandas as pd
import numpy as np
from sklearn.linear_model import SGDClassifier
from sklearn.preprocessing import StandardScaler
from sklearn.metrics import classification_report, roc_auc_score
from sklearn.utils.class_weight import compute_class_weight

###############################################################################
# CONFIG
###############################################################################
DATA_FILE = "risk_training_data.csv"   # <- change this to new CSV each session
MODEL_FILE = "death_model.pkl"        # <- model+scaler bundle saved here
LABEL_WINDOW = 10.0                   # seconds ahead to define "die soon"
###############################################################################

print(f"[info] loading data from {DATA_FILE}")
df = pd.read_csv(DATA_FILE)
df = df.sort_values(["name", "t"]).reset_index(drop=True)

###############################################################################
# 1. Build offline labels (will_die_10s_offline)
###############################################################################

df["will_die_10s_offline"] = 0

for name, group in df.groupby("name"):
    times = group["t"].to_numpy()
    dead_flags = group["is_dead"].to_numpy()

    for i in range(len(times)):
        # skip rows where they're already dead
        if dead_flags[i]:
            continue

        t_i = times[i]

        # check any future row <= LABEL_WINDOW seconds where they become dead
        future_idxs = np.where(
            (times - t_i > 0) &
            (times - t_i <= LABEL_WINDOW) &
            (dead_flags == True)
        )[0]

        if len(future_idxs) > 0:
            df.loc[group.index[i], "will_die_10s_offline"] = 1

pos_count = int(df["will_die_10s_offline"].sum())
print(f"[info] relabel complete. positives={pos_count} / {len(df)} total rows")

###############################################################################
# 2. Filter to usable training rows
#
# - only your champ (hp_pct >= 0 means we actually recorded your HP)
# - only frames where you're currently alive
###############################################################################

train_df = df[(df["hp_pct"] >= 0) & (df["is_dead"] == False)].copy()

print(f"[info] candidate training rows (alive self only): {len(train_df)}")

# fill missing numeric features
train_df["gold"] = train_df["gold"].fillna(-1.0)
train_df["kills"] = train_df["kills"].fillna(0)
train_df["deaths"] = train_df["deaths"].fillna(0)
train_df["assists"] = train_df["assists"].fillna(0)
train_df["cs"] = train_df["cs"].fillna(0)

feature_cols = [
    "hp_pct",
    "level",
    "deaths",
    "kills",
    "assists",
    "cs",
    "gold",
]

X_raw = train_df[feature_cols].to_numpy()
y = train_df["will_die_10s_offline"].astype(int).to_numpy()

print(f"[info] X_raw shape={X_raw.shape}, positives in y={y.sum()}")

if len(y) == 0:
    raise RuntimeError("No training rows available. Play/collect more and re-run.")

###############################################################################
# 3. Load previous model+scaler OR initialize new
###############################################################################

if os.path.exists(MODEL_FILE):
    print(f"[info] loading existing model from {MODEL_FILE}")
    bundle = joblib.load(MODEL_FILE)
    scaler = bundle["scaler"]
    clf = bundle["clf"]
    prev_feature_cols = bundle["feature_cols"]

    # sanity check: make sure columns didn't change
    if prev_feature_cols != feature_cols:
        raise RuntimeError(
            f"Feature column mismatch!\nold: {prev_feature_cols}\nnew: {feature_cols}"
        )

    # transform new batch with existing scaler
    X = scaler.transform(X_raw)

    # compute class weights for THIS batch
    classes = np.array([0, 1])
    weights = compute_class_weight(
        class_weight="balanced",
        classes=classes,
        y=y
    )
    class_weight_dict = {cls: w for cls, w in zip(classes, weights)}

    # manually apply class weights by repeating samples
    # (partial_fit in SGDClassifier can't take class_weight='balanced')
    sample_weights = np.vectorize(class_weight_dict.get)(y)

    clf.partial_fit(X, y, classes=classes, sample_weight=sample_weights)

else:
    print("[info] no previous model found, creating new scaler+SGDClassifier")
    scaler = StandardScaler()
    X = scaler.fit_transform(X_raw)

    clf = SGDClassifier(
        loss="log_loss",        # logistic regression style
        max_iter=1,             # we'll call partial_fit manually
        learning_rate="optimal",
        random_state=42,
    )

    classes = np.array([0, 1])

    # compute balanced weights manually for first batch
    weights = compute_class_weight(
        class_weight="balanced",
        classes=classes,
        y=y
    )
    class_weight_dict = {cls: w for cls, w in zip(classes, weights)}
    sample_weights = np.vectorize(class_weight_dict.get)(y)

    clf.partial_fit(X, y, classes=classes, sample_weight=sample_weights)

###############################################################################
# 4. Evaluate on THIS batch (quick sanity check)
###############################################################################

# predictions on this current batch
y_pred = clf.predict(X)

# get "probability of dying soon"
if hasattr(clf, "predict_proba"):
    y_prob = clf.predict_proba(X)[:, 1]
else:
    # fallback if predict_proba isn't available for some reason
    scores = clf.decision_function(X)
    y_prob = 1 / (1 + np.exp(-scores))

print("\n=== performance on this batch ===")
print(classification_report(y, y_pred, digits=4))

try:
    auc = roc_auc_score(y, y_prob)
    print(f"AUC: {auc:.4f}")
except Exception as e:
    print("AUC could not be computed:", e)

# "importance" for linear model = coefficient magnitude
coef = clf.coef_[0]
print("\n=== feature weights (bigger abs = more impact) ===")
for feat, weight in sorted(zip(feature_cols, coef), key=lambda x: abs(x[1]), reverse=True):
    print(f"{feat:10s} -> {weight:+.4f}")

###############################################################################
# 5. Save updated model bundle
###############################################################################

bundle = {
    "scaler": scaler,
    "clf": clf,
    "feature_cols": feature_cols,
}
joblib.dump(bundle, MODEL_FILE)
print(f"\n✅ saved updated model to {MODEL_FILE}")
