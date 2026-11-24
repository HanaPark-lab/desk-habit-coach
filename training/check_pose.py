"""촬영 클립 검사: 사람 검출률, 관절 가시성, 30 Step 확보 여부, 파일명 규칙.

사용:
  python training/check_pose.py data/raw                      # 폴더 전체
  python training/check_pose.py data/raw/A005_sit_stand --preview out/preview
  python training/check_pose.py clip.mp4

FAIL = 학습에 쓸 수 없음(다시 촬영), WARN = 쓸 수는 있지만 확인 필요.
"""
import argparse
import re
import sys
from collections import Counter
from pathlib import Path

import cv2
from ultralytics import YOLO

SEQ_LEN = 30          # 모델 입력 Step 수 (docs/DATA_COLLECTION_GUIDE.md 1장)
TARGET_FPS = 6.0      # 30 Step = 5초
VIS_CONF = 0.5        # 이 값 이상이면 관절이 '보인다'고 판단
# 앉은 상반신 촬영 기준. COCO 17 index: 5/6 어깨, 7/8 팔꿈치, 9/10 손목, 11/12 골반
# 무릎·발목은 책상에 가려지는 게 정상이라 검사하지 않음
KEY_JOINTS = {"어깨": (5, 6), "팔꿈치": (7, 8), "손목": (9, 10), "골반": (11, 12)}
LEAVES_FRAME = {"walk_turn_walk", "sit_stand"}  # 걷기·일어나기는 화면 밖으로 나가는 게 정상 (폴더의 라벨 기준)
NAME_RE = re.compile(r"^P\d{2}_(top|bottom)_R\d{2}\.mp4$", re.IGNORECASE)  # 사람_각도_반복. top = 모니터 위, bottom = 모니터 아래
DIR_RE = re.compile(r"^[AX]\d{3}_[a-z_]+$")  # A001_drink_return = 학습 (ID_라벨), X001_... = NG 영상 (학습 제외)


def judge(action, name_ok, dir_ok, duration, steps, person_ratio, multi_ratio, joint_ratio):
    """측정값 → (상태, 문제 목록). 기준을 바꾸려면 여기만 수정."""
    fails, warns = [], []
    if steps < SEQ_LEN:
        fails.append(f"너무 짧음: {steps} Step < {SEQ_LEN} (5초 이상 필요)")
    min_person = 0.4 if action in LEAVES_FRAME else 0.8
    if person_ratio < min_person:
        fails.append(f"사람 검출 {person_ratio:.0%} ({min_person:.0%} 미만)")
    for joint, ratio in joint_ratio.items():
        if ratio < 0.7:
            warns.append(f"{joint} 보임 {ratio:.0%} (잘림·가림?)")
    if multi_ratio > 0.1:
        warns.append(f"2명 이상 검출 {multi_ratio:.0%}")
    if duration > 10:
        warns.append(f"길이 {duration:.1f}s (10초 초과, 한 파일 = 동작 1회?)")
    if not name_ok:
        warns.append("파일명 규칙 불일치 (P01_top_R01.mp4 또는 P01_bottom_R01.mp4)")
    if not dir_ok:
        warns.append("폴더명 규칙 불일치 (A001_bend_return 등)")
    return ("FAIL" if fails else "WARN" if warns else "PASS"), fails + warns


def check_clip(model, path, preview_dir=None):
    cap = cv2.VideoCapture(str(path))
    if not cap.isOpened():
        return "FAIL", ["영상을 열 수 없음 (손상·코덱 문제)"]
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    stride = max(1, round(fps / TARGET_FPS))
    mid = (total // 2) // stride * stride

    steps = detected = multi = 0
    visible = Counter()
    idx = 0
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        if idx % stride == 0:
            steps += 1
            r = model.predict(frame, verbose=False)[0]
            n = len(r.boxes)
            if n:
                detected += 1
                multi += n > 1
                # 가장 큰 사람 = 촬영 대상
                main = int(r.boxes.xywh[:, 2:].prod(dim=1).argmax())
                conf = r.keypoints.conf[main]
                for joint, ids in KEY_JOINTS.items():
                    visible[joint] += all(conf[i] >= VIS_CONF for i in ids)
            if preview_dir and idx == mid:
                cv2.imwrite(str(Path(preview_dir) / f"{path.parent.name}__{path.stem}.jpg"), r.plot())
        idx += 1
    cap.release()
    if steps == 0:
        return "FAIL", ["프레임을 읽지 못함"]

    joint_ratio = {j: visible[j] / detected for j in KEY_JOINTS} if detected else {}
    if "_bottom_" in path.name.lower():
        joint_ratio.pop("골반", None)  # 모니터 아래 카메라는 책상 모서리에 골반이 가려지는 게 정상
    return judge(
        action=path.parent.name.partition("_")[2],  # "A003_walk_turn_walk" → "walk_turn_walk"
        name_ok=bool(NAME_RE.match(path.name)),
        dir_ok=bool(DIR_RE.match(path.parent.name)),
        duration=idx / fps,
        steps=steps,
        person_ratio=detected / steps,
        multi_ratio=multi / max(detected, 1),
        joint_ratio=joint_ratio,
    )


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("target", type=Path, help="mp4 파일 또는 폴더")
    ap.add_argument("--weights", default="ai_service/models/yolo11n-pose.pt")
    ap.add_argument("--preview", type=Path, help="가운데 프레임 Skeleton 이미지 저장 폴더")
    args = ap.parse_args()

    clips = [args.target] if args.target.is_file() else sorted(args.target.rglob("*.mp4"))
    if not clips:
        sys.exit(f"mp4 파일이 없습니다: {args.target}")
    if args.preview:
        args.preview.mkdir(parents=True, exist_ok=True)

    model = YOLO(args.weights)
    status_count, per_class = Counter(), Counter()
    for clip in clips:
        status, problems = check_clip(model, clip, args.preview)
        status_count[status] += 1
        if status != "FAIL":
            per_class[clip.parent.name] += 1
        print(f"[{status}] {clip.parent.name}/{clip.name}")
        for p in problems:
            print(f"        - {p}")

    print("\n== 요약 ==", dict(status_count))
    print("== 사용 가능 클립 수(동작별) ==")
    for cls, n in sorted(per_class.items()):
        print(f"  {cls}: {n}")
    sys.exit(1 if status_count["FAIL"] else 0)


if __name__ == "__main__":
    # 판정 규칙 자체 검사 (모델 없이 즉시 실행됨)
    ok_joints = {j: 1.0 for j in KEY_JOINTS}
    assert judge("drink_return", True, True, 6, 36, 1.0, 0, ok_joints)[0] == "PASS"
    assert judge("drink_return", True, True, 3, 18, 1.0, 0, ok_joints)[0] == "FAIL"
    assert judge("drink_return", True, True, 6, 36, 0.5, 0, ok_joints)[0] == "FAIL"
    assert judge("walk_turn_walk", True, True, 6, 36, 0.5, 0, ok_joints)[0] == "PASS"  # 걷기는 화면 이탈 허용
    assert judge("drink_return", True, True, 6, 36, 1.0, 0, {**ok_joints, "골반": 0.3})[0] == "WARN"
    assert judge("drink_return", False, True, 6, 36, 1.0, 0, ok_joints)[0] == "WARN"
    assert NAME_RE.match("P01_top_R03.mp4") and NAME_RE.match("P02_bottom_R10.mp4")
    assert not NAME_RE.match("P01_S01_top_R03.mp4") and not NAME_RE.match("clip1.mp4")
    assert DIR_RE.match("A001_drink_return") and DIR_RE.match("X004_scratch_head")
    assert not DIR_RE.match("A01_wave") and not DIR_RE.match("walk_turn_walk")
    main()
