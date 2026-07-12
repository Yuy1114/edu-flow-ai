"""V3.5 single-stage placement model.

Contract:
  input  = teaching-task features
  output = TopK detailed resource placements: classroom_name | day_of_week | period_index

This baseline uses one LightGBM multiclass model to directly predict resource_key.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import lightgbm as lgb
import pandas as pd
from sklearn.model_selection import GroupShuffleSplit

REPO_ROOT = Path(__file__).resolve().parents[3]
DATA_PATH = REPO_ROOT / "backend" / "models" / "v3.5" / "placement" / "clean_training_samples.jsonl"
OUTPUT_DIR = REPO_ROOT / "backend" / "models" / "v3.5" / "placement_single"
MODEL_PATH = OUTPUT_DIR / "single_resource_lgbm.txt"
META_PATH = OUTPUT_DIR / "placement_single_meta.json"

RESOURCE_KEY = "resource_key"
ROOM_LABEL = "classroom_name"
SLOT_LABEL = "slot_label"
LABEL = "label_id"

TEXT_FEATURES = [
    "course_name",
    "course_code",
    "teacher_no",
    "teacher_name",
    "class_name",
    "class_major",
    "class_department",
    "course_type",
    "required_room_type",
]
NUMERIC_FEATURES = ["class_grade", "class_no", "student_count", "total_hours"]
FEATURES = [f"{feature}_code" for feature in TEXT_FEATURES] + NUMERIC_FEATURES


@dataclass(frozen=True)
class PlacementCandidate:
    resource_key: str
    classroom_name: str
    day_of_week: int
    period_index: int
    score: float
    source: str = "single_lgbm"

    @property
    def slot_score(self) -> float:
        return self.score

    @property
    def room_score(self) -> float:
        return self.score

    def to_dict(self) -> dict[str, Any]:
        return {
            "resource_key": self.resource_key,
            "classroom_name": self.classroom_name,
            "day_of_week": self.day_of_week,
            "period_index": self.period_index,
            "score": self.score,
            "slot_score": self.slot_score,
            "room_score": self.room_score,
            "source": self.source,
        }


class V35SinglePlacementModel:
    def __init__(self, model: lgb.Booster, meta: dict[str, Any]) -> None:
        self.model = model
        self.meta = meta
        self.resource_by_label = {int(key): value for key, value in meta["resource_by_label"].items()}
        self.resource_meta = meta.get("resources", {})
        self.room_meta = meta.get("rooms", {})

    @classmethod
    def load(cls, model_dir: Path = OUTPUT_DIR) -> "V35SinglePlacementModel":
        meta_path = model_dir / "placement_single_meta.json"
        if not meta_path.exists():
            raise FileNotFoundError(f"V3.5 single placement meta not found: {meta_path}")
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        model = lgb.Booster(model_file=meta["model_path"])
        return cls(model=model, meta=meta)

    def predict_topk(self, task_like: dict[str, Any], *, top_k: int = 40, slot_top_k: int | None = None) -> list[PlacementCandidate]:
        row = _encode_task_row(task_like)
        frame = pd.DataFrame([row], columns=FEATURES)
        probabilities = self.model.predict(frame)[0]
        required_room_type = str(task_like.get("required_room_type") or "").strip()

        candidates: list[PlacementCandidate] = []
        ranked = sorted(range(len(probabilities)), key=lambda index: float(probabilities[index]), reverse=True)
        for label_id in ranked:
            resource_key = self.resource_by_label.get(int(label_id))
            if not resource_key:
                continue
            meta = self.resource_meta.get(resource_key) or _parse_resource_key(resource_key)
            if not meta:
                continue
            room = str(meta["classroom_name"])
            if required_room_type and not self._room_matches(room, required_room_type):
                continue
            candidates.append(
                PlacementCandidate(
                    resource_key=resource_key,
                    classroom_name=room,
                    day_of_week=int(meta["day_of_week"]),
                    period_index=int(meta["period_index"]),
                    score=float(probabilities[label_id]),
                )
            )
            if len(candidates) >= top_k:
                break
        return candidates

    def _room_matches(self, room_name: str, required_room_type: str) -> bool:
        room = self.room_meta.get(str(room_name), {})
        classroom_type = str(room.get("classroom_type") or "").strip()
        return not classroom_type or classroom_type == required_room_type


def train(data_path: Path = DATA_PATH, output_dir: Path = OUTPUT_DIR, *, rounds: int = 160) -> Path:
    if not data_path.exists():
        raise FileNotFoundError(f"Training samples not found: {data_path}")

    raw_df = _load_training_frame(data_path)
    resource_keys = sorted(raw_df[RESOURCE_KEY].astype(str).unique())
    label_by_resource = {resource: index for index, resource in enumerate(resource_keys)}
    df = _build_feature_frame(raw_df, label_by_resource)

    train_idx, test_idx = _group_split(df)
    train_df = df.iloc[train_idx].copy()
    test_df = df.iloc[test_idx].copy()

    train_data = lgb.Dataset(train_df[FEATURES], label=train_df[LABEL])
    test_data = lgb.Dataset(test_df[FEATURES], label=test_df[LABEL], reference=train_data)
    params = {
        "objective": "multiclass",
        "metric": "multi_logloss",
        "num_class": len(resource_keys),
        "boosting_type": "gbdt",
        "num_leaves": 63,
        "learning_rate": 0.05,
        "feature_fraction": 0.9,
        "bagging_fraction": 0.85,
        "bagging_freq": 5,
        "min_child_samples": 5,
        "verbose": -1,
        "num_threads": 4,
    }
    model = lgb.train(
        params,
        train_data,
        valid_sets=[test_data],
        num_boost_round=rounds,
        callbacks=[lgb.early_stopping(20), lgb.log_evaluation(50)],
    )

    output_dir.mkdir(parents=True, exist_ok=True)
    model_path = output_dir / "single_resource_lgbm.txt"
    model.save_model(str(model_path))

    meta = {
        "model_type": "v3.5_lightgbm_single_resource_placement",
        "version": "0.1",
        "training_data": str(data_path),
        "model_path": str(model_path),
        "features": FEATURES,
        "text_features": TEXT_FEATURES,
        "label_by_resource": label_by_resource,
        "resource_by_label": {str(index): resource for resource, index in label_by_resource.items()},
        "contract": {
            "input": TEXT_FEATURES + NUMERIC_FEATURES,
            "output": ["resource_key", "classroom_name", "day_of_week", "period_index", "score"],
        },
        "training_samples": int(len(df)),
        "source_key_count": int(df["source_key"].nunique()),
        "resource_key_count": int(len(resource_keys)),
        "slot_count": int(df[SLOT_LABEL].nunique()),
        "room_count": int(df[ROOM_LABEL].nunique()),
        "rooms": _room_meta(df),
        "resources": _resource_meta(df),
    }
    loaded_model = V35SinglePlacementModel(model=model, meta=meta)
    meta["metrics"] = _evaluate(test_df, loaded_model)

    meta_path = output_dir / "placement_single_meta.json"
    meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"训练样本: {len(df)}")
    print(f"resource 类别: {len(resource_keys)}")
    print(f"slot 类别: {df[SLOT_LABEL].nunique()}")
    print(f"room 类别: {df[ROOM_LABEL].nunique()}")
    print("评估结果:")
    for key, value in meta["metrics"].items():
        print(f"{key}: {value:.4f}")
    print(f"模型目录: {output_dir}")
    return meta_path


def predict_sample(meta_dir: Path = OUTPUT_DIR, data_path: Path = DATA_PATH, *, index: int = 0, top_k: int = 20) -> list[dict[str, Any]]:
    df = _load_training_frame(data_path)
    if index < 0 or index >= len(df):
        raise IndexError(f"index out of range: {index}, samples={len(df)}")
    model = V35SinglePlacementModel.load(meta_dir)
    row = df.iloc[index].to_dict()
    candidates = model.predict_topk(row, top_k=top_k)
    return [candidate.to_dict() for candidate in candidates]


def _load_training_frame(data_path: Path) -> pd.DataFrame:
    if data_path.suffix == ".jsonl":
        rows = [json.loads(line) for line in data_path.read_text(encoding="utf-8").splitlines() if line.strip()]
        df = pd.DataFrame(rows)
    else:
        df = pd.read_csv(data_path)
    df.columns = [str(column).strip() for column in df.columns]
    for column in TEXT_FEATURES + [ROOM_LABEL, RESOURCE_KEY]:
        df[column] = df.get(column, "").astype(str).fillna("").str.strip()
    for column in NUMERIC_FEATURES + ["day_of_week", "period_index", "classroom_capacity"]:
        if column in df.columns:
            df[column] = pd.to_numeric(df[column], errors="coerce").fillna(0)
    df = df[df[RESOURCE_KEY].astype(str).str.strip() != ""].copy()
    df = df[df[ROOM_LABEL].astype(str).str.strip() != ""].copy()
    df = df[(df["day_of_week"] > 0) & (df["period_index"] > 0)].copy()
    df[SLOT_LABEL] = df["day_of_week"].astype(int).astype(str) + "|" + df["period_index"].astype(int).astype(str)
    df[RESOURCE_KEY] = df[ROOM_LABEL].astype(str) + "|" + df["day_of_week"].astype(int).astype(str) + "|" + df["period_index"].astype(int).astype(str)
    return df


def _build_feature_frame(raw_df: pd.DataFrame, label_by_resource: dict[str, int]) -> pd.DataFrame:
    df = raw_df.copy()
    for feature in TEXT_FEATURES:
        df[f"{feature}_code"] = df[feature].map(_stable_code).astype(float)
    for feature in NUMERIC_FEATURES:
        df[feature] = pd.to_numeric(df[feature], errors="coerce").fillna(0)
    df[LABEL] = df[RESOURCE_KEY].map(label_by_resource).astype(int)
    return df


def _encode_task_row(task_like: dict[str, Any]) -> dict[str, float]:
    aliases = {
        "class_name": ["class_name", "class_group", "class_group_names"],
        "class_major": ["class_major", "class_group_majors"],
        "class_department": ["class_department", "class_group_departments"],
        "class_grade": ["class_grade", "class_group_grades"],
    }
    row: dict[str, float] = {}
    for feature in TEXT_FEATURES:
        row[f"{feature}_code"] = float(_stable_code(_first_present(task_like, aliases.get(feature, [feature]), "")))
    for feature in NUMERIC_FEATURES:
        row[feature] = _safe_float(_first_present(task_like, aliases.get(feature, [feature]), 0))
    return row


def _first_present(source: dict[str, Any], keys: list[str], default: Any) -> Any:
    for key in keys:
        value = source.get(key)
        if value not in (None, ""):
            return value
    return default


def _stable_code(value: Any, modulo: int = 10007) -> int:
    text = str(value or "").strip().lower().replace(" ", "")
    if not text:
        return 0
    total = 0
    for char in text:
        total = (total * 131 + ord(char)) % modulo
    return total + 1


def _safe_float(value: Any) -> float:
    if isinstance(value, str) and "," in value:
        value = value.split(",")[0]
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _group_split(df: pd.DataFrame):
    splitter = GroupShuffleSplit(n_splits=1, test_size=0.2, random_state=42)
    return next(splitter.split(df, groups=df["source_key"].astype(str)))


def _evaluate(test_df: pd.DataFrame, model: V35SinglePlacementModel) -> dict[str, float]:
    hits = {1: 0, 5: 0, 10: 0, 30: 0}
    slot_hits = {1: 0, 3: 0, 5: 0}
    total = 0
    for _source_key, group in test_df.groupby("source_key", dropna=False):
        truth_resources = set(group[RESOURCE_KEY].astype(str).tolist())
        truth_slots = set(group[SLOT_LABEL].astype(str).tolist())
        task = group.iloc[0].to_dict()
        predictions = model.predict_topk(task, top_k=30)
        predicted_resources = [candidate.resource_key for candidate in predictions]
        predicted_slots = [f"{candidate.day_of_week}|{candidate.period_index}" for candidate in predictions]
        total += 1
        for k in hits:
            if truth_resources & set(predicted_resources[:k]):
                hits[k] += 1
        for k in slot_hits:
            if truth_slots & set(predicted_slots[:k]):
                slot_hits[k] += 1
    denominator = max(1, total)
    metrics = {f"hit@{k}": hits[k] / denominator for k in hits}
    metrics.update({f"slot_hit@{k}": slot_hits[k] / denominator for k in slot_hits})
    return {key: round(float(value), 6) for key, value in metrics.items()}


def _room_meta(df: pd.DataFrame) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for room_name, group in df.groupby(ROOM_LABEL):
        row = group.iloc[0]
        result[str(room_name)] = {
            "classroom_name": str(room_name),
            "classroom_type": str(row.get("classroom_type") or ""),
            "classroom_capacity": int(_safe_float(row.get("classroom_capacity", 0))),
        }
    return result


def _resource_meta(df: pd.DataFrame) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for resource_key, group in df.groupby(RESOURCE_KEY):
        row = group.iloc[0]
        result[str(resource_key)] = {
            "resource_key": str(resource_key),
            "classroom_name": str(row[ROOM_LABEL]),
            "day_of_week": int(row["day_of_week"]),
            "period_index": int(row["period_index"]),
            "classroom_type": str(row.get("classroom_type") or ""),
            "classroom_capacity": int(_safe_float(row.get("classroom_capacity", 0))),
        }
    return result


def _parse_resource_key(resource_key: str) -> dict[str, Any] | None:
    parts = str(resource_key).split("|")
    if len(parts) != 3:
        return None
    try:
        return {
            "resource_key": resource_key,
            "classroom_name": parts[0],
            "day_of_week": int(parts[1]),
            "period_index": int(parts[2]),
        }
    except ValueError:
        return None


def main() -> None:
    parser = argparse.ArgumentParser(description="V3.5 single-stage placement model")
    subparsers = parser.add_subparsers(dest="command", required=True)

    train_parser = subparsers.add_parser("train")
    train_parser.add_argument("--data", default=str(DATA_PATH))
    train_parser.add_argument("--output-dir", default=str(OUTPUT_DIR))
    train_parser.add_argument("--rounds", type=int, default=160)

    predict_parser = subparsers.add_parser("predict-sample")
    predict_parser.add_argument("--data", default=str(DATA_PATH))
    predict_parser.add_argument("--model-dir", default=str(OUTPUT_DIR))
    predict_parser.add_argument("--index", type=int, default=0)
    predict_parser.add_argument("--top-k", type=int, default=20)

    args = parser.parse_args()
    if args.command == "train":
        train(data_path=Path(args.data), output_dir=Path(args.output_dir), rounds=args.rounds)
    elif args.command == "predict-sample":
        predictions = predict_sample(Path(args.model_dir), Path(args.data), index=args.index, top_k=args.top_k)
        print(json.dumps(predictions, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
