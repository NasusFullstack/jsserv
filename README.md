# jsserv — 춥채팅 전투 중계 서버

[춥채팅](https://github.com/NasusFullstack/chat)에서 '배틀크루저 소환' 치트로 사람끼리
전투를 붙일 때, 조작을 서로에게 넘겨주는 중계 서버입니다.

**평소에는 아무도 접속하지 않습니다.** 치트를 친 순간에만 붙었다가 전투가 끝나면 끊습니다.

## 왜 서버로 중계하는가

직접 연결(P2P)도 가능하지만 실사용에서 두 가지가 걸립니다.

| | 직접 연결 | 서버 중계 |
|---|---|---|
| 상대에게 내 IP가 보이는가 | 보임 | **안 보임** |
| 둘 다 공유기 뒤에 있으면 | **연결 실패** | 됨 |
| 윈도우 방화벽 허용 창 | 뜸 | 안 뜸 |

## 지금 상태

연결이 되는지 확인하는 단계입니다. 중계 기능은 아직 없습니다.

| 주소 | 하는 일 |
|---|---|
| `GET /` | 배포가 돌고 있는지 + 버전 |
| `GET /health` | 살아있는지 |
| `WS /ws` | 받은 글을 그대로 돌려줌. 붙는 즉시 어떤 헤더가 살아서 왔는지 알려줌 |

`/ws`가 핵심입니다. nginx가 `proxy_pass`만 있고 Upgrade 헤더를 안 넘기면 WebSocket이
막히는데, 그러면 실시간 전투를 다른 방법으로 짜야 합니다. 막혔다면 nginx에 두 줄이
필요합니다.

```nginx
proxy_set_header Upgrade $http_upgrade;
proxy_set_header Connection "upgrade";
```

## 실행

```
pip install -r requirements.txt
uvicorn app:app --host 0.0.0.0 --port 8000     # 또는  python app.py
```
