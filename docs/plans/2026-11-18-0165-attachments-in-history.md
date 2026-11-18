# Attachments in chat history (v0.1.65)

**Owner:** ②Main (product lane). Decided 2026-11-18: no change in v0.1.64. A label-only stopgap was considered and dropped, because it adds nothing a user can use.

## The problem
When you send an image, a link or a file, the sent bubble shows a thumbnail or a preview chip. After you switch conversations or reopen the app, the same message shows only a text line such as `[图片:name.png]`.

This is by design today:
- The thumbnail is a session-only echo (`addUserMessage(text, display)` in `web/src/App.tsx`).
- The image goes to the model for that turn only (decision ③A).
- `persisted_user_text` in `server/orchestrator/arslan.py` stores a placeholder line, never the bytes. Base64 in a text column would bloat the database and every backup.

Link previews and document chips are session-only in the same way.

## What v0.1.65 should do
- **Store sent attachments as files** under Arslan's data folder, per conversation. The message row keeps references (id, name, kind, size, mime), not bytes.
- **Show them again on reload:** an image's thumbnail, a link's preview card, a document's chip. They are served through an authenticated local endpoint. No new network exposure: the same origin rules as the rest of the API.
- **Keep the model honest.** On later turns the model still gets the placeholder line, so it never implies it can still see an image. Re-attaching is explicit.
- **Retention:** delete with the conversation; follow the user's backup and data-folder rules; define a size cap.
- **Phone:** decide whether the iPhone shows the stored thumbnails, a Bridge frame change. If not, it keeps today's text.
- **Privacy docs:** say that sent attachments are now kept locally.
- **Mock first:** this changes how the chat looks after a reload, so the bubble design needs a mock before the build.
- **Review level:** it adds stored user content and a file-serving endpoint, so it is security surface and gets a max review.
