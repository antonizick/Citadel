from app.storage.markdown_store import MarkdownStore


class UserStore(MarkdownStore):
    def __init__(self):
        super().__init__("data/users")

    def get_by_username(self, username: str) -> dict | None:
        for user in self.list():
            if user.get("username", "").lower() == username.lower():
                return user
        return None

    def username_exists(self, username: str, exclude_id: str | None = None) -> bool:
        for user in self.list():
            if user.get("username", "").lower() == username.lower():
                if exclude_id and user.get("id") == exclude_id:
                    continue
                return True
        return False


users_store = UserStore()
