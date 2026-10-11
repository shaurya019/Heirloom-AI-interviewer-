"""Summary tree storage. Every parent/child link change is a single TransactWriteItems call,
so a parent's child_ids and each child's parent_id can never disagree.
"""
from __future__ import annotations

import hashlib
from typing import Any, Sequence

from boto3.dynamodb.conditions import Key
from botocore.exceptions import ClientError

from app.db import keys
from app.db.codec import from_ddb, to_ddb
from app.models.summary import SummaryNode, SummaryTree, SummaryTreeNode

MAX_TXN_ITEMS = 100


def node_id_for(session_id: str, level: int, first_message_id: str, last_message_id: str) -> str:
    """Deterministic id: re-summarizing the same message range targets the same item (idempotency)."""
    raw = f"{session_id}|L{level}|{first_message_id}|{last_message_id}"
    return f"n{level}_" + hashlib.sha1(raw.encode()).hexdigest()[:20]


def session_node_id(session_id: str) -> str:
    return "n2_" + hashlib.sha1(f"{session_id}|L2".encode()).hexdigest()[:20]


def archive_node_id(user_id: str) -> str:
    return "n3_" + hashlib.sha1(f"{user_id}|L3".encode()).hexdigest()[:20]


def archive_session_id(user_id: str) -> str:
    return f"{keys.ARCHIVE_SESSION}-{user_id}"


def _item(n: SummaryNode) -> dict[str, Any]:
    d = n.model_dump(mode="json")
    d.update({"pk": keys.session_pk(n.session_id), "sk": keys.node_sk(n.level, n.first_seq, n.node_id),
              "entity": "summary_node", "gsi1pk": keys.node_by_id_gsi1pk(n.node_id), "gsi1sk": keys.NODE_GSI1SK})
    if n.parent_id:
        d["gsi2pk"] = keys.children_gsi2pk(n.parent_id)
        d["gsi2sk"] = keys.children_gsi2sk(n.first_seq, n.node_id)
    if d.get("parent_id") is None:
        d.pop("parent_id", None)
        d.pop("parent_level", None)
    return d


def _node(item: dict[str, Any]) -> SummaryNode:
    d = from_ddb(item)
    return SummaryNode.model_validate({k: v for k, v in d.items() if k in SummaryNode.model_fields})


class TxnConflict(Exception):
    """A conditional check inside a transaction failed (already done, or concurrent writer)."""

    def __init__(self, reasons: list[str]):
        super().__init__(", ".join(reasons))
        self.reasons = reasons


class SummaryNodeRepository:
    def __init__(self, table: Any):
        self.table = table
        self.client = table.meta.client

    # ----------------------------------------------------------------- reads
    def get(self, node_id: str) -> SummaryNode | None:
        r = self.table.query(IndexName="GSI1", KeyConditionExpression=Key("gsi1pk").eq(keys.node_by_id_gsi1pk(node_id)))
        return _node(r["Items"][0]) if r["Items"] else None

    def get_consistent(self, n: SummaryNode) -> SummaryNode | None:
        it = self.table.get_item(Key={"pk": keys.session_pk(n.session_id),
                                      "sk": keys.node_sk(n.level, n.first_seq, n.node_id)},
                                 ConsistentRead=True).get("Item")
        return _node(it) if it else None

    def list_session(self, session_id: str, level: int | None = None) -> list[SummaryNode]:
        prefix = keys.node_level_prefix(level) if level is not None else "NODE#"
        out: list[SummaryNode] = []
        kw: dict[str, Any] = {"KeyConditionExpression": Key("pk").eq(keys.session_pk(session_id))
                              & Key("sk").begins_with(prefix), "ConsistentRead": True}
        while True:
            r = self.table.query(**kw)
            out += [_node(i) for i in r["Items"]]
            if "LastEvaluatedKey" not in r:
                return out
            kw["ExclusiveStartKey"] = r["LastEvaluatedKey"]

    def children(self, parent_id: str) -> list[SummaryNode]:
        r = self.table.query(IndexName="GSI2", KeyConditionExpression=Key("gsi2pk").eq(keys.children_gsi2pk(parent_id)))
        return [_node(i) for i in r["Items"]]

    def unparented(self, session_id: str, level: int) -> list[SummaryNode]:
        """Level-`level` nodes without a parent at level+1 (a level-2 'catch-all' parent doesn't count)."""
        return sorted([n for n in self.list_session(session_id, level)
                       if n.parent_id is None or (n.parent_level is not None and n.parent_level > level + 1)],
                      key=lambda n: n.first_seq)

    # ----------------------------------------------------------------- transactions
    def _transact(self, items: list[dict[str, Any]]) -> None:
        if len(items) > MAX_TXN_ITEMS:
            raise ValueError(f"transaction too large ({len(items)} > {MAX_TXN_ITEMS})")
        try:
            self.client.transact_write_items(TransactItems=items)
        except ClientError as e:
            if e.response["Error"]["Code"] == "TransactionCanceledException":
                reasons = [r.get("Code", "None") for r in e.response.get("CancellationReasons", [])]
                raise TxnConflict(reasons) from e
            raise

    def _put(self, n: SummaryNode, *, must_not_exist: bool) -> dict[str, Any]:
        put: dict[str, Any] = {"TableName": self.table.name, "Item": to_ddb(_item(n))}
        if must_not_exist:
            put["ConditionExpression"] = "attribute_not_exists(pk)"
        return {"Put": put}

    def _link_child(self, child: SummaryNode, parent: SummaryNode, allowed_old_parent: str | None) -> dict[str, Any]:
        cond = "attribute_exists(pk) AND (attribute_not_exists(parent_id)"
        vals: dict[str, Any] = {":p": parent.node_id, ":pl": parent.level,
                                ":g2": keys.children_gsi2pk(parent.node_id),
                                ":g2s": keys.children_gsi2sk(child.first_seq, child.node_id)}
        if allowed_old_parent:
            cond += " OR parent_id = :old"
            vals[":old"] = allowed_old_parent
        cond += " OR parent_id = :p)"
        return {"Update": {
            "TableName": self.table.name,
            "Key": {"pk": keys.session_pk(child.session_id),
                    "sk": keys.node_sk(child.level, child.first_seq, child.node_id)},
            "UpdateExpression": "SET parent_id = :p, parent_level = :pl, gsi2pk = :g2, gsi2sk = :g2s",
            "ConditionExpression": cond, "ExpressionAttributeValues": vals}}

    def commit_leaf(self, leaf: SummaryNode, session_update: dict[str, Any]) -> None:
        """Leaf node + rolling-summary/buffer advance, atomically."""
        self._transact([self._put(leaf, must_not_exist=True), session_update])

    def commit_parent(self, parent: SummaryNode, children: Sequence[SummaryNode], *, replace: bool,
                      detach_from: SummaryNode | None = None) -> None:
        """Create (or replace) a parent and point every child at it, in one transaction.

        detach_from: a level-2/3 catch-all parent that currently owns some of `children`; its child_ids are
        rewritten in the same transaction so the old link disappears atomically.
        """
        items = [self._put(parent, must_not_exist=not replace)]
        old = detach_from.node_id if detach_from else None
        items += [self._link_child(c, parent, old if c.parent_id == old else None) for c in children]
        if detach_from is not None:
            moved = {c.node_id for c in children}
            remaining = [i for i in detach_from.child_ids if i not in moved] + [parent.node_id]
            items.append({"Update": {
                "TableName": self.table.name,
                "Key": {"pk": keys.session_pk(detach_from.session_id),
                        "sk": keys.node_sk(detach_from.level, detach_from.first_seq, detach_from.node_id)},
                "UpdateExpression": "SET child_ids = :c, version = version + :one",
                "ConditionExpression": "version = :v",
                "ExpressionAttributeValues": {":c": remaining, ":one": 1, ":v": detach_from.version}}})
            # new parent becomes a child of the catch-all parent
            parent.parent_id, parent.parent_level = detach_from.node_id, detach_from.level
            items[0] = self._put(parent, must_not_exist=not replace)
        self._transact(items)

    # ----------------------------------------------------------------- tree
    def tree(self, session_id: str) -> list[SummaryTreeNode]:
        nodes = {n.node_id: SummaryTreeNode(**n.model_dump()) for n in self.list_session(session_id)}
        roots: list[SummaryTreeNode] = []
        for n in sorted(nodes.values(), key=lambda x: (x.first_seq, -x.level)):
            parent = nodes.get(n.parent_id) if n.parent_id else None
            (parent.children if parent else roots).append(n)
        for n in nodes.values():
            n.children.sort(key=lambda c: c.first_seq)
        return sorted(roots, key=lambda r: (-r.level, r.first_seq))

    def verify_links(self, session_id: str) -> list[str]:
        """Return a list of integrity violations (empty == consistent)."""
        nodes = {n.node_id: n for n in self.list_session(session_id)}
        errs: list[str] = []
        for n in nodes.values():
            if n.parent_id and n.parent_id in nodes and n.node_id not in nodes[n.parent_id].child_ids:
                errs.append(f"{n.node_id}.parent={n.parent_id} but parent.child_ids lacks it")
            for c in n.child_ids:
                if c not in nodes:
                    if not c.startswith("n2_"):  # cross-session children live in other partitions (L3)
                        errs.append(f"{n.node_id} lists missing child {c}")
                elif nodes[c].parent_id != n.node_id:
                    errs.append(f"{n.node_id} lists {c} but child's parent is {nodes[c].parent_id}")
        return errs


def build_tree_response(repo: SummaryNodeRepository, session: Any) -> SummaryTree:
    return SummaryTree(session_id=session.session_id, roots=repo.tree(session.session_id),
                       rolling_summary=session.rolling_summary, rolling_summary_tokens=session.rolling_summary_tokens,
                       buffer_start_seq=session.buffer_start_seq, msg_count=session.msg_count)
