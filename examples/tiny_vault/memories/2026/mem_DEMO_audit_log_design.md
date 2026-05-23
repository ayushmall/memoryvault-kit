---
id: mem_DEMO_audit_log_design
title: "Audit logs design doc landed"
type: reference
entities: ["[[Audit Logs]]", "[[Sara Kim]]"]
tags: [audit-logs, design, reference]
source_host: manual
source_ref: "demo"
importance: 0.7
confidence: 1.0
created: 2026-03-20
status: active
---

Sara published the audit log design. Format: append-only, JSON Lines, signed. One entry per read/write with user_id, action, resource, timestamp. Cited as reference for Acme conversation.
