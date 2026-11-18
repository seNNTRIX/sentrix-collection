# experiments/

실험 하나 = `experiments/<실험ID>/` 폴더 하나. 같은 설정으로 다시 돌리면 같은 결과가 나와야 한다.

각 폴더에 남길 것:

- `config.yaml`: 데이터 버전(파일 해시), feature 버전, window 크기, 모델, 하이퍼파라미터, seed, 분할 방법, 코드 커밋
- `results.json`: fold별·전체 지표, 신뢰구간
- `notes.md`: 목적, 결론, 이전 실험과의 차이

실험 ID 형식: `<YYYYMMDD>-<짧은-설명>` (예: `20261028-baseline-random`).

데이터(`data/`)와 큰 생성물은 git에 올리지 않는다.
