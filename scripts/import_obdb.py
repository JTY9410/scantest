"""OBDb(https://github.com/OBDb) 현대·기아·제네시스 전동화 차종의 BMS(7E4) 신호 정의를 가져온다.

OBDb 데이터는 CC BY-SA 4.0이다. 가져온 파일(app/modules/canlab/engine/obdb/*.json)도 같은 라이선스로 두고
obdb/NOTICE에 출처·변경 내용을 남긴다. 실행: python scripts/import_obdb.py (인터넷 필요, 결과는 커밋한다)
변환 규칙은 app/modules/canlab/engine/obdb.py에 있다(관리자 화면의 참고자료 'OBDb 동기화'와 같다).
"""

import json
import subprocess
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.modules.canlab.engine.obdb import MODELS, RAW_URL, convert  # noqa: E402

OUT = ROOT / "app/modules/canlab/engine/obdb"
GIT = "https://github.com/OBDb/{repo}.git"


def _get(url: str) -> bytes:
    with urllib.request.urlopen(url, timeout=30) as response:
        return response.read()


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    written = []
    for repo in MODELS:
        sha = subprocess.run(["git", "ls-remote", GIT.format(repo=repo), "HEAD"], capture_output=True, text=True,
                             check=True, timeout=60).stdout.split()[0]
        result = convert(repo, sha, json.loads(_get(RAW_URL.format(repo=repo, ref=sha))))
        if result is None:
            print(f"{repo}: BMS(7E4) 신호 없음, 건너뜀")
            continue
        (OUT / f"{repo}.json").write_text(json.dumps(result, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        written.append(f"- {repo} @ {sha[:12]}: 신호 {len(result['signals'])}개, 셀 {len(result['cells'])}개")
        print(written[-1])
    license_text = _get("https://raw.githubusercontent.com/OBDb/Hyundai-Kona-Electric/main/LICENSE").decode()
    (OUT / "LICENSE").write_text(license_text, encoding="utf-8")
    (OUT / "NOTICE").write_text(
        "이 폴더의 차종별 JSON은 OBDb(https://github.com/OBDb) 신호 정의에서 만든 2차 저작물이며\n"
        "원본과 같은 Creative Commons Attribution-ShareAlike 4.0(CC BY-SA 4.0, LICENSE)을 따릅니다.\n\n"
        "변경 내용: BMS(7E4) 22 DID 신호 중 바이트 단위 신호만 골라 위스캔 신호 키·바이트 배치(start·width·scale)·정상 범위(min·max)로\n"
        "바꾸고, 차량정보 모델명 매칭 키워드를 더했습니다. 원본 저장소와 커밋은 각 파일의 repo·commit에 있습니다.\n\n"
        + "\n".join(written) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
