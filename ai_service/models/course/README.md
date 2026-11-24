# 교과 6종 RF 모델 (course 프로필)

교과에서 제공한 기존 6종 모델 파일 3개를 이 폴더에 넣는다. **아직 확보하지 못함 (미완료).**

- `rf_action_baseline.joblib`
- `rf_feature_columns.json` (1,140개, `t00_...` 순서가 `ai_service/src/sequence_utils.py`와 같아야 함)
- `rf_training_info.json` (`classes` 6종, `sequence_steps` 30, `features_per_step` 38, `target_fps` 6.0, `window_stride_steps` 6)

실행: `.env`에 `MODEL_PROFILE=course` 후 FastAPI 재시작. 로딩 시 규격이 다르면 서버가 시작되지 않는다.
교과 모델 결과는 분석 화면에 동작으로만 표시하고 음료·움직임 습관 기록에는 쓰지 않는다.
