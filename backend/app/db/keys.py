"""Single-table key design for Heirloom.

Table: `heirloom`  (pk, sk)  + GSI1 (gsi1pk, gsi1sk) + GSI2 (gsi2pk, gsi2sk) + GSI3 (gsi3pk, gsi3sk, sparse)

Entity            pk                     sk                                   GSI1 / GSI2 / GSI3
----------------  ---------------------  -----------------------------------  ---------------------------------------------
User              USER#<uid>             PROFILE
Session           SESSION#<sid>          META                                 GSI1: USER#<uid>#SESSIONS / <created_at>
Message           SESSION#<sid>          MSG#<seq:08d>
Summary node      SESSION#<sid>          NODE#L<level>#<first_seq:08d>#<nid>  GSI1: NODE#<nid> / NODE        (get by id)
                                                                              GSI2: CHILDREN#<parent_id> / <first_seq:08d>#<nid>
Memory            MEMORY#<mid>           MEMORY                               GSI1: USER#<uid>#MEMORIES / <created_at>#<mid>
                                                                              GSI3 (sparse): VECTOR#pending / <created_at>#<mid>
Open question     USER#<uid>             OPENQ#<qid>                          (status attribute)
Asked question    USER#<uid>             ASKED#<created_at>#<qid>             (text; vector in 'questions')
Chapter           USER#<uid>             CHAPTER#<created_at>#<cid>
Agent run         SESSION#<sid>          RUN#<created_at>#<rid>
Embedding cache   EMBCACHE#<model>       <sha256(text)>

Access patterns:
  messages by session, in order    -> Query pk=SESSION#sid, sk begins_with MSG#   (seq gives order + cursor)
  summary nodes by session & level -> Query pk=SESSION#sid, sk begins_with NODE#L<level>#
  children of a node               -> Query GSI2 gsi2pk=CHILDREN#<parent_id>
  node by id                       -> Query GSI1 gsi1pk=NODE#<nid>
  memories by user in time range   -> Query GSI1 gsi1pk=USER#uid#MEMORIES, gsi1sk BETWEEN t0 AND t1~
  memory by id                     -> GetItem pk=MEMORY#mid, sk=MEMORY   (BatchGetItem for hydration)
  agent runs by session            -> Query pk=SESSION#sid, sk begins_with RUN#
  pending vector writes            -> Scan/Query GSI3 gsi3pk=VECTOR#pending (sparse: only pending items)
  open questions by user/status    -> Query pk=USER#uid, sk begins_with OPENQ#, filter status
"""
from __future__ import annotations

SEQ_WIDTH = 8
ARCHIVE_SESSION = "ARCHIVE"  # pseudo-session for level-3 life-archive summaries


def _seq(n: int) -> str:
    if n < 0:
        raise ValueError("sequence must be non-negative")
    return f"{n:0{SEQ_WIDTH}d}"


# ---- users -----------------------------------------------------------------
def user_pk(user_id: str) -> str:
    return f"USER#{user_id}"


USER_SK = "PROFILE"


# ---- sessions --------------------------------------------------------------
def session_pk(session_id: str) -> str:
    return f"SESSION#{session_id}"


SESSION_SK = "META"


def user_sessions_gsi1pk(user_id: str) -> str:
    return f"USER#{user_id}#SESSIONS"


# ---- messages --------------------------------------------------------------
MSG_PREFIX = "MSG#"


def message_sk(seq: int) -> str:
    return f"{MSG_PREFIX}{_seq(seq)}"


def seq_from_message_sk(sk: str) -> int:
    return int(sk.removeprefix(MSG_PREFIX))


# ---- summary nodes ---------------------------------------------------------
def node_level_prefix(level: int) -> str:
    return f"NODE#L{level}#"


def node_sk(level: int, first_seq: int, node_id: str) -> str:
    return f"{node_level_prefix(level)}{_seq(first_seq)}#{node_id}"


def node_by_id_gsi1pk(node_id: str) -> str:
    return f"NODE#{node_id}"


NODE_GSI1SK = "NODE"


def children_gsi2pk(parent_id: str) -> str:
    return f"CHILDREN#{parent_id}"


def children_gsi2sk(first_seq: int, node_id: str) -> str:
    return f"{_seq(first_seq)}#{node_id}"


# ---- memories --------------------------------------------------------------
def memory_pk(memory_id: str) -> str:
    return f"MEMORY#{memory_id}"


MEMORY_SK = "MEMORY"


def user_memories_gsi1pk(user_id: str) -> str:
    return f"USER#{user_id}#MEMORIES"


def memory_time_gsi1sk(created_at_iso: str, memory_id: str) -> str:
    return f"{created_at_iso}#{memory_id}"


VECTOR_PENDING_GSI3PK = "VECTOR#pending"


# ---- open questions (contradictions) --------------------------------------
# sk is deterministic per contradiction (qid = hash of the memory pair + field), so re-detecting the same
# conflict is a no-op conditional put. Status is an attribute (open|asked|resolved), filtered on read.
OPENQ_PREFIX = "OPENQ#"


def open_question_sk(qid: str) -> str:
    return f"{OPENQ_PREFIX}{qid}"


# ---- interviewer question ledger (never repeat a question) -----------------
ASKED_PREFIX = "ASKED#"


def asked_question_sk(created_at_iso: str, qid: str) -> str:
    return f"{ASKED_PREFIX}{created_at_iso}#{qid}"


# ---- chapters ----------------------------------------------------------------
CHAPTER_PREFIX = "CHAPTER#"


def chapter_sk(created_at_iso: str, chapter_id: str) -> str:
    return f"{CHAPTER_PREFIX}{created_at_iso}#{chapter_id}"


# ---- agent runs ------------------------------------------------------------
RUN_PREFIX = "RUN#"


def agent_run_sk(created_at_iso: str, run_id: str) -> str:
    return f"{RUN_PREFIX}{created_at_iso}#{run_id}"


# ---- embedding cache -------------------------------------------------------
def embcache_pk(model: str) -> str:
    return f"EMBCACHE#{model}"
