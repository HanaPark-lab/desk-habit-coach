"""촬영 영상 → YOLO Pose → 38 Feature × 30 Step Window → Random Forest 학습.

클래스: A### 폴더의 동작 + X### 폴더(NG 행동)를 모두 묶은 `other`(기타).
1) 교차검증 두 가지
   - 처음 보는 사람: 한 사람의 영상을 전부 빼고 학습 → 그 사람의 동작 영상 평가
   - 처음 보는 기타 행동: NG 행동 하나(폴더)를 통째로 빼고 학습 → 그 행동이 습관으로 잘못 인정되는지 평가
2) 모든 영상으로 최종 모델 학습 → ai_service/models/ 의 파일 3개 교체 (FastAPI 재시작하면 적용)
3) 교차검증 점수로 습관별 기준값 제안
결과 요약: docs/TRAINING_REPORT.md

실행 (프로젝트 폴더에서):  .venv/bin/python training/train_rf.py
"""
import json
import re
import sys
import time
from datetime import date
from pathlib import Path

import joblib
import numpy as np
import sklearn
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import confusion_matrix
from ultralytics import YOLO

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "ai_service"))
from services.pose_pipeline import track_people  # noqa: E402  추론(FastAPI)과 같은 Pose·Feature 코드
from src.feature_utils import FEATURES_PER_STEP  # noqa: E402
from src.sequence_utils import (  # noqa: E402
    SEQ_STEPS, TARGET_FPS, WINDOW_STRIDE, active_windows, feature_columns, windows,
)

RAW = ROOT / "data" / "raw"
CACHE = ROOT / "out" / "feature_cache"
OUT = ROOT / "ai_service" / "models"
REPORT = ROOT / "docs" / "TRAINING_REPORT.md"
NAME_RE = re.compile(r"^(P\d{2})_(top|bottom)_R\d{2}$", re.IGNORECASE)
OTHER = "other"  # X### 폴더 전체 = 학습한 습관이 아닌 행동
# 서비스 행동 묶음. backend/analyses/habits.py 의 EVENT_LABELS와 같게 유지
HABITS = {"DRINK": ["drink_return"], "MOVEMENT": ["wave", "walk_turn_walk"]}
BASE_THRESHOLD = 0.5


def find_clips():
    clips = []
    for folder in sorted(p for p in RAW.iterdir() if p.is_dir() and re.match(r"^[AX]\d{3}_", p.name)):
        ng = folder.name[0] == "X"
        for f in sorted(folder.glob("*.mp4")):
            m = NAME_RE.match(f.stem)
            if not m:
                print(f"  건너뜀 (파일명 규칙 불일치): {folder.name}/{f.name}")
                continue
            clips.append({"path": f, "folder": folder.name, "id": folder.name[:4], "ng": ng,
                          "label": OTHER if ng else folder.name.partition("_")[2],
                          "person": m[1].upper(), "angle": m[2].lower()})
    return clips


def clip_windows(pose, clip):
    """영상 → 촬영 대상(가장 오래 잡힌 사람)의 Window 배열. Pose 추출은 오래 걸려서 캐시한다."""
    cache = CACHE / f"{clip['folder']}__{clip['path'].stem}.npy"
    if cache.exists() and cache.stat().st_mtime >= clip["path"].stat().st_mtime:
        return np.load(cache)
    tracks, _ = track_people(pose, clip["path"])
    if tracks:
        main = max(tracks.values(), key=lambda steps: sum(s is not None for s in steps))
        X = windows(main)
    else:
        X = np.empty((0, SEQ_STEPS * FEATURES_PER_STEP), np.float32)
    CACHE.mkdir(parents=True, exist_ok=True)
    np.save(cache, X)
    return X


def fit(clips):
    X = np.vstack([c["X"] for c in clips])
    y = np.concatenate([[c["label"]] * len(c["X"]) for c in clips])
    model = RandomForestClassifier(n_estimators=300, min_samples_leaf=2, class_weight="balanced", random_state=0, n_jobs=-1)
    return model.fit(X, y)


def predict_clips(model, clips):
    """서비스와 같은 방식: Window 확률 평균 → 영상별 {라벨: 확률}, 최고 라벨."""
    for c in clips:
        c["oof"] = dict(zip(model.classes_, model.predict_proba(c["X"]).mean(axis=0)))
        c["pred"] = max(c["oof"], key=c["oof"].get)


def top_habit(proba):
    scores = {h: sum(proba.get(label, 0.0) for label in labels) for h, labels in HABITS.items()}
    habit = max(scores, key=scores.get)
    return habit, scores[habit]


def main():
    clips = find_clips()
    pose = YOLO(str(OUT / "yolo11n-pose.pt"))
    start = time.time()
    for i, c in enumerate(clips, 1):
        c["X"] = active_windows(clip_windows(pose, c))  # 쉬는 구간 제외 (추론과 같은 규칙)
        print(f"[{i}/{len(clips)}] {c['folder']}/{c['path'].name}: Window {len(c['X'])}")
    print(f"Feature 추출 {time.time() - start:.0f}초")

    usable = [c for c in clips if len(c["X"])]
    skipped = [c for c in clips if not len(c["X"])]
    actions = [c for c in usable if not c["ng"]]
    ng = [c for c in usable if c["ng"]]
    persons = sorted({c["person"] for c in actions})
    behaviors = sorted({c["folder"] for c in ng})
    classes = sorted({c["label"] for c in usable})

    # 1-a) 처음 보는 사람: 그 사람의 영상(동작·NG 모두)을 빼고 학습
    person_folds = []
    for p in persons:
        test = [c for c in actions if c["person"] == p]
        predict_clips(fit([c for c in usable if c["person"] != p]), test)
        person_folds.append((p, len(test), sum(c["pred"] == c["label"] for c in test)))
    # 1-b) 처음 보는 기타 행동: NG 행동 하나를 통째로 빼고 학습
    behavior_folds = []
    for b in behaviors:
        test = [c for c in ng if c["folder"] == b]
        predict_clips(fit([c for c in usable if c["folder"] != b]), test)
        behavior_folds.append((b, len(test), sum(c["pred"] == OTHER for c in test)))

    action_acc = sum(c["pred"] == c["label"] for c in actions) / len(actions)
    other_acc = sum(c["pred"] == OTHER for c in ng) / len(ng) if ng else 0.0
    angle_acc = {a: np.mean([c["pred"] == c["label"] for c in actions if c["angle"] == a]) for a in ("top", "bottom")}
    cm = confusion_matrix([c["label"] for c in usable], [c["pred"] for c in usable], labels=classes)
    wrong = [c for c in usable if c["pred"] != c["label"]]

    # 2) 최종 모델 (모든 영상)
    final = fit(usable)

    # 3) 기준값: '처음 본' NG 영상이 각 습관으로 나온 최고 점수보다 조금 위 (교차검증 점수 사용)
    ng_habits = [(c, *top_habit(c["oof"])) for c in ng]
    thresholds = {}
    for habit, labels in HABITS.items():
        ng_scores = [s for _, h, s in ng_habits if h == habit]
        ng_max = max(ng_scores, default=0.0)
        suggested = round(min(0.95, max(BASE_THRESHOLD, ng_max + 0.05)), 2)
        positives = [top_habit(c["oof"]) for c in actions if c["label"] in labels]
        passed = sum(h == habit and s >= suggested for h, s in positives)
        thresholds[habit] = {
            "ng_max": round(float(ng_max), 3), "suggested": float(suggested), "recall": f"{passed}/{len(positives)}",
            "ng_at_base": sum(s >= BASE_THRESHOLD for s in ng_scores),
        }

    # 저장 (가짜 모델과 같은 파일 이름·형식)
    action_ids = dict(sorted({c["id"]: c["label"] for c in actions}.items()))
    info = {
        "model_version": f"rf-{date.today().isoformat()}-other",
        "is_dummy": False,
        "classes": [str(c) for c in final.classes_],
        "action_ids": {**action_ids, "X***": OTHER},
        "sequence_steps": SEQ_STEPS,
        "features_per_step": FEATURES_PER_STEP,
        "n_features": len(feature_columns()),
        "target_fps": TARGET_FPS,
        "window_stride_steps": WINDOW_STRIDE,
        "sklearn_version": sklearn.__version__,
        "created_at": date.today().isoformat(),
        "train_clips": len(usable),
        "train_windows": int(sum(len(c["X"]) for c in usable)),
        "persons": persons,
        "cv_action_accuracy": round(action_acc, 3),
        "cv_other_rejection": round(other_acc, 3),
        "suggested_thresholds": {h: t["suggested"] for h, t in thresholds.items()},
    }
    OUT.mkdir(parents=True, exist_ok=True)
    joblib.dump(final, OUT / "rf_action_baseline.joblib")
    (OUT / "rf_feature_columns.json").write_text(json.dumps(feature_columns(), indent=1), encoding="utf-8")
    (OUT / "rf_training_info.json").write_text(json.dumps(info, indent=2, ensure_ascii=False), encoding="utf-8")

    # 보고서
    lines = [
        "# 학습 결과 보고서", "",
        f"- 생성: `training/train_rf.py` · {info['created_at']} · 모델 `{info['model_version']}`",
        f"- 입력: {SEQ_STEPS} Step × {FEATURES_PER_STEP} Feature = {info['n_features']} · {TARGET_FPS:g}fps (5초 Window, 1초 간격) · 쉬는 구간 Window 제외",
        "- 모델: RandomForest(n_estimators=300, min_samples_leaf=2, class_weight=balanced)",
        f"- 클래스: {', '.join(f'`{c}`' for c in classes)} (`other` = X### 폴더의 NG 행동 전체)", "",
        "## 데이터", "", "| 폴더 | 라벨 | 영상 | Window | 사람 | top / bottom |", "|---|---|---:|---:|---|---|",
    ]
    for folder in sorted({c["folder"] for c in usable}):
        cs = [c for c in usable if c["folder"] == folder]
        lines.append(f"| {folder} | `{cs[0]['label']}` | {len(cs)} | {sum(len(c['X']) for c in cs)} | {', '.join(sorted({c['person'] for c in cs}))} "
                     f"| {sum(c['angle'] == 'top' for c in cs)} / {sum(c['angle'] == 'bottom' for c in cs)} |")
    if skipped:
        lines += ["", "Window가 없어 제외된 영상 (사람이 5초 이상 잡히지 않음): " + ", ".join(f"`{c['folder']}/{c['path'].name}`" for c in skipped)]
    lines += ["", "## 교차검증", "", "### 처음 보는 사람 (동작 영상)", "",
              "한 사람의 영상을 전부 빼고 학습한 뒤 그 사람을 평가한다.", "",
              "| 평가한 사람 | 영상 | 정답 | 정확도 |", "|---|---:|---:|---:|"]
    lines += [f"| {p} | {n} | {k} | {k / n:.1%} |" for p, n, k in person_folds]
    lines += [f"| **전체** | {len(actions)} | {sum(k for _, _, k in person_folds)} | **{action_acc:.1%}** |", "",
              f"카메라 각도별: top {angle_acc['top']:.1%} · bottom {angle_acc['bottom']:.1%}", "",
              "### 처음 보는 기타 행동 (NG 영상)", "",
              "NG 행동 하나를 통째로 빼고 학습한 뒤, 그 행동이 `other`로 걸러지는지 평가한다.", "",
              "| 뺀 행동 | 영상 | `other`로 걸러짐 |", "|---|---:|---:|"]
    lines += [f"| {b} | {n} | {k} |" for b, n, k in behavior_folds]
    lines += [f"| **전체** | {len(ng)} | **{sum(k for _, _, k in behavior_folds)} ({other_acc:.1%})** |", "",
              "### 혼동행렬 (행 = 실제, 열 = 예측, 교차검증)", "",
              "| 실제 \\ 예측 | " + " | ".join(f"`{c}`" for c in classes) + " |", "|---|" + "---:|" * len(classes)]
    lines += [f"| `{classes[i]}` | " + " | ".join(str(v) for v in row) + " |" for i, row in enumerate(cm)]
    if wrong:
        lines += ["", "틀린 영상: " + ", ".join(f"`{c['folder']}/{c['path'].name}` → `{c['pred']}`" for c in wrong)]
    lines += ["", "## 습관 기준값", "",
              "처음 본 NG 영상이 각 습관으로 나온 최고 점수보다 조금 높게 잡는다 (최소 0.5).",
              "'통과'는 처음 보는 사람의 동작 영상 중 그 기준에서 제대로 인정되는 수, 'NG 잘못 인정'은 기준 0.5일 때 습관으로 잘못 인정됐을 NG 영상 수다.", "",
              "| 습관 | NG 최고 점수 | 제안 기준값 | 통과 | 기준 0.5일 때 NG 잘못 인정 |", "|---|---:|---:|---:|---:|"]
    lines += [f"| {h} | {t['ng_max']:.2f} | **{t['suggested']:.2f}** | {t['recall']} | {t['ng_at_base']} |" for h, t in thresholds.items()]
    lines += ["", "`.env`에 반영:", "", "```dotenv"] + [f"EVENT_THRESHOLD_{h}={t['suggested']}" for h, t in thresholds.items()] + ["```", "",
              "### NG 영상별 결과 (처음 본 행동으로 평가)", "", "| 영상 | 예측 | 가장 높은 습관 | 점수 |", "|---|---|---|---:|"]
    lines += [f"| `{c['folder']}/{c['path'].name}` | `{c['pred']}` | {h} | {s:.2f} |" for c, h, s in ng_habits]
    lines += ["", "> NG 영상이 P01·top 한 사람·한 각도뿐이고 전체 데이터도 적다. 이 숫자는 이 촬영 환경에서의 참고값이며 일반적인 정확도를 보장하지 않는다."]
    REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")

    print(f"\n처음 보는 사람 동작 정확도 {action_acc:.1%} (top {angle_acc['top']:.1%}, bottom {angle_acc['bottom']:.1%})")
    for p, n, k in person_folds:
        print(f"  {p}: {k}/{n}")
    print(f"처음 보는 NG 행동 → other {other_acc:.1%}")
    for h, t in thresholds.items():
        print(f"  {h}: NG 최고 {t['ng_max']:.2f} → 기준 {t['suggested']} · 통과 {t['recall']} · (0.5일 때 NG 잘못 인정 {t['ng_at_base']})")
    print(f"저장: {OUT} · 보고서: {REPORT}")


if __name__ == "__main__":
    main()
