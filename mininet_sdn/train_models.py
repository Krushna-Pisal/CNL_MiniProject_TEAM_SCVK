"""
train_models.py
Offline training step (run this once before starting the adaptive
controller): trains the same Random Forest TrafficClassifier used in the
simulation on synthetic labelled flow data, and pickles it to
models/classifier.pkl so controller_adaptive.py can load it and classify
REAL flows (using real byte/packet counts pulled from OFPFlowStatsRequest)
at runtime.

    python3 train_models.py
"""

import os
import pickle
import json

from ml_models import TrafficClassifier
from traffic_gen_synthetic import generate_flows, HOST_PAIRS

MODELS_DIR = os.path.join(os.path.dirname(__file__), "models")


def main():
    os.makedirs(MODELS_DIR, exist_ok=True)
    df = generate_flows(1500, HOST_PAIRS, seed=1)

    clf = TrafficClassifier()
    metrics = clf.fit(df)

    with open(os.path.join(MODELS_DIR, "classifier.pkl"), "wb") as f:
        pickle.dump(clf, f)

    with open(os.path.join(MODELS_DIR, "classifier_metrics.json"), "w") as f:
        json.dump({
            "accuracy": metrics["accuracy"],
            "labels": metrics["labels"],
            "confusion_matrix": metrics["confusion_matrix"],
            "feature_importance": metrics["feature_importance"],
        }, f, indent=2)

    print(f"Trained classifier. Held-out accuracy: {metrics['accuracy']*100:.1f}%")
    print(f"Saved to {MODELS_DIR}/classifier.pkl")


if __name__ == "__main__":
    main()
