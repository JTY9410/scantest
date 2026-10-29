# PostgreSQL 시드

`supabase_baseline.dump`는 PostgreSQL custom-format 덤프입니다. Compose의
`db` 데이터 볼륨이 비어 있어 Postgres가 `/docker-entrypoint-initdb.d`를 실행하는
최초 기동 때만 복원됩니다.

## 개인정보 주의

시드에는 개인정보와 운영성 데이터가 포함될 수 있습니다. 저장소는 비공개로 유지하고,
승인된 배포 경로 밖으로 덤프 파일을 공유하지 마세요. 새 덤프를 만들기 전에는 포함
데이터와 취급 기준을 다시 확인하세요.

## 내보내기

Supabase Direct(non-pooler) 데이터베이스 URL이 있을 때만 실행합니다.

```sh
SUPABASE_DATABASE_URL='postgresql://...' ./scripts/export_supabase_seed.sh
```

스크립트는 PostgreSQL 16 호환 `pg_dump` 클라이언트로 `public` 스키마만
소유권/ACL 없이 내보내고 `data/seed/supabase_baseline.dump`에 저장합니다.
URL 없이 임의 자격 증명을 만들거나 덤프를 생성하지 마세요.

## 복원 동작

- 시드 파일이 없거나 0바이트이면 개발용 빈 DB로 시작합니다. 이 상태도 로컬 개발에는
  허용됩니다.
- 복원은 **빈 볼륨 최초 기동 때만** 적용됩니다. 기존 Mac 볼륨
  `wecarscan_dh_pgdata`가 남아 있으면 시드를 추가하거나 바꿔도 다시 복원되지 않습니다.
- 복원 실패 후 새로 시도해야 한다면 `docker compose down -v` 후 다시
  `docker compose up`을 실행합니다. 이 명령은 기존 DB 볼륨과 데이터를 삭제하는
  파괴적 작업입니다.
