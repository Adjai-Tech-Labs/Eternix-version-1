from uuid import uuid4

import pytest

from eternix.core.models import Capability, CapabilityStatus, ModelInfo, Objective, Task, TaskStatus
from eternix.core.task_store import TaskStore
from eternix.tools.command import register_command_tools
from eternix.tools.filesystem import register_filesystem_tools
from eternix.tools.registry import execute_tool, tool_registry


@pytest.fixture
def task_store(tmp_path):
    db_path = tmp_path / "test.db"
    store = TaskStore(db_path)
    yield store


@pytest.fixture
def registered_tools():
    register_filesystem_tools()
    register_command_tools()
    yield
    tool_registry._tools.clear()
    tool_registry._handlers.clear()


class TestTaskStore:
    def test_create_and_get_objective(self, task_store):
        obj = Objective(
            id=uuid4(),
            user_input="Test objective",
            description="Test description",
            desired_end_state="Done",
        )
        task_store.create_objective(obj)
        retrieved = task_store.get_objective(obj.id)
        assert retrieved is not None
        assert retrieved.user_input == "Test objective"

    def test_create_and_get_task(self, task_store):
        obj = Objective(
            id=uuid4(),
            user_input="Test",
            description="Test",
            desired_end_state="Done",
        )
        task_store.create_objective(obj)

        task = Task(
            id=uuid4(),
            objective_id=obj.id,
            description="Test task",
            capability="test",
            tool_id="test.tool",
        )
        task_store.create_task(task)
        retrieved = task_store.get_task(task.id)
        assert retrieved is not None
        assert retrieved.description == "Test task"

    def test_update_task_status(self, task_store):
        obj = Objective(
            id=uuid4(),
            user_input="Test",
            description="Test",
            desired_end_state="Done",
        )
        task_store.create_objective(obj)

        task = Task(
            id=uuid4(),
            objective_id=obj.id,
            description="Test task",
            capability="test",
        )
        task_store.create_task(task)

        task.status = TaskStatus.COMPLETED
        task_store.update_task(task)
        retrieved = task_store.get_task(task.id)
        assert retrieved.status == TaskStatus.COMPLETED


class TestConversations:
    def test_create_and_get_conversation(self, task_store):
        conv_id, title = task_store.create_conversation("Test Conv")
        assert conv_id is not None
        assert title == "Test Conv"
        conv = task_store.get_conversation(conv_id)
        assert conv is not None
        assert conv.title == "Test Conv"
        assert conv.messages == []

    def test_create_conversation_with_objective(self, task_store):
        obj = Objective(
            id=uuid4(),
            user_input="Test",
            description="Test",
            desired_end_state="Done",
        )
        task_store.create_objective(obj)
        conv_id, _ = task_store.create_conversation("Obj Conv", objective_id=obj.id)
        conv = task_store.get_conversation(conv_id)
        assert conv is not None
        assert conv.objective_id == str(obj.id)

    def test_list_conversations(self, task_store):
        task_store.create_conversation("Conv 1")
        task_store.create_conversation("Conv 2")
        list_result = task_store.list_conversations()
        assert len(list_result) == 2

    def test_add_and_retrieve_message(self, task_store):
        conv_id, _ = task_store.create_conversation("Msg Test")
        msg_id = task_store.add_message(conv_id, "user", "Hello")
        assert msg_id is not None
        conv = task_store.get_conversation(conv_id)
        assert len(conv.messages) == 1
        assert conv.messages[0].role == "user"
        assert conv.messages[0].content == "Hello"

    def test_delete_conversation(self, task_store):
        conv_id, _ = task_store.create_conversation("Delete Me")
        assert task_store.delete_conversation(conv_id) is True
        assert task_store.get_conversation(conv_id) is None

    def test_rename_conversation(self, task_store):
        conv_id, _ = task_store.create_conversation("Old Title")
        result = task_store.rename_conversation(conv_id, "New Title")
        assert result is not None
        assert result["title"] == "New Title"
        conv = task_store.get_conversation(conv_id)
        assert conv.title == "New Title"

    def test_message_order(self, task_store):
        conv_id, _ = task_store.create_conversation("Order Test")
        task_store.add_message(conv_id, "user", "First")
        task_store.add_message(conv_id, "assistant", "Second")
        task_store.add_message(conv_id, "user", "Third")
        conv = task_store.get_conversation(conv_id)
        assert len(conv.messages) == 3
        assert conv.messages[0].content == "First"
        assert conv.messages[1].content == "Second"
        assert conv.messages[2].content == "Third"


class TestWorkspaces:
    def test_create_workspace(self, task_store, tmp_path):
        ws = task_store.create_workspace("Test Project", str(tmp_path))
        assert ws["id"] is not None
        assert ws["name"] == "Test Project"
        assert ws["path"] == str(tmp_path.resolve())
        assert ws["active"] is False

    def test_create_workspace_duplicate_path(self, task_store, tmp_path):
        ws1 = task_store.create_workspace("First", str(tmp_path))
        ws2 = task_store.create_workspace("Second", str(tmp_path))
        assert ws1["id"] == ws2["id"]

    def test_list_workspaces(self, task_store, tmp_path):
        sub1 = tmp_path / "proj1"
        sub2 = tmp_path / "proj2"
        sub1.mkdir()
        sub2.mkdir()
        task_store.create_workspace("Proj 1", str(sub1))
        task_store.create_workspace("Proj 2", str(sub2))
        list_result = task_store.list_workspaces()
        assert len(list_result) == 2

    def test_get_workspace(self, task_store, tmp_path):
        ws = task_store.create_workspace("Test", str(tmp_path))
        retrieved = task_store.get_workspace(ws["id"])
        assert retrieved is not None
        assert retrieved["name"] == "Test"

    def test_delete_workspace(self, task_store, tmp_path):
        ws = task_store.create_workspace("Test", str(tmp_path))
        assert task_store.delete_workspace(ws["id"]) is True
        assert task_store.get_workspace(ws["id"]) is None

    def test_set_active_workspace(self, task_store, tmp_path):
        ws1 = task_store.create_workspace("Proj 1", str(tmp_path / "p1"))
        ws2 = task_store.create_workspace("Proj 2", str(tmp_path / "p2"))
        task_store.set_active_workspace(ws2["id"])
        list_result = task_store.list_workspaces()
        for w in list_result:
            if w["id"] == ws2["id"]:
                assert w["active"] is True
            else:
                assert w["active"] is False


class TestTools:
    @pytest.mark.asyncio
    async def test_fs_list(self, task_store, registered_tools):
        task = Task(
            id=uuid4(),
            objective_id=uuid4(),
            description="Test",
            capability="filesystem",
            tool_id="fs.list",
            input_data={"path": "."},
        )
        result = await execute_tool("fs.list", task, {"path": "."}, task_store)
        assert result.success
        assert "entries" in result.output

    @pytest.mark.asyncio
    async def test_fs_write_and_read(self, task_store, registered_tools, tmp_path):
        test_file = tmp_path / "test_write.txt"
        task = Task(
            id=uuid4(),
            objective_id=uuid4(),
            description="Test write",
            capability="filesystem",
            tool_id="fs.write",
            input_data={"path": str(test_file), "content": "Hello World"},
        )
        result = await execute_tool("fs.write", task, {"path": str(test_file), "content": "Hello World"}, task_store)
        assert result.success

        task2 = Task(
            id=uuid4(),
            objective_id=uuid4(),
            description="Test read",
            capability="filesystem",
            tool_id="fs.read",
            input_data={"path": str(test_file)},
        )
        result2 = await execute_tool("fs.read", task2, {"path": str(test_file)}, task_store)
        assert result2.success
        assert result2.output["content"] == "Hello World"

    @pytest.mark.asyncio
    async def test_cmd_exec(self, task_store, registered_tools):
        task = Task(
            id=uuid4(),
            objective_id=uuid4(),
            description="Test cmd",
            capability="command",
            tool_id="cmd.exec",
            input_data={"command": "echo", "args": ["hello"]},
        )
        result = await execute_tool("cmd.exec", task, {"command": "echo", "args": ["hello"]}, task_store)
        assert result.success
        assert result.exit_code == 0
        assert "hello" in result.stdout


class TestCapabilityManagement:
    def test_upsert_and_get_capability(self, task_store):
        cap = Capability(
            id="test_cap",
            name="Test Capability",
            description="A test capability",
            status=CapabilityStatus.AVAILABLE,
            required_tools=["tool1", "tool2"],
        )
        task_store.upsert_capability(cap)
        retrieved = task_store.get_capability("test_cap")
        assert retrieved is not None
        assert retrieved.name == "Test Capability"
        assert retrieved.status == CapabilityStatus.AVAILABLE

    def test_list_capabilities(self, task_store):
        cap1 = Capability(id="cap1", name="Cap 1", description="First", status=CapabilityStatus.AVAILABLE)
        cap2 = Capability(id="cap2", name="Cap 2", description="Second", status=CapabilityStatus.MISSING)
        task_store.upsert_capability(cap1)
        task_store.upsert_capability(cap2)
        caps = task_store.list_capabilities()
        assert len(caps) == 2


class TestModelManagement:
    def test_upsert_and_get_model(self, task_store):
        model = ModelInfo(
            id="test_model",
            name="Test Model",
            path="/path/to/model.gguf",
            format="gguf",
            size_bytes=1000000,
            context_length=4096,
            capabilities=["completion"],
            runtime="llama.cpp",
            available=True,
        )
        task_store.upsert_model(model)
        retrieved = task_store.get_model("test_model")
        assert retrieved is not None
        assert retrieved.name == "Test Model"
        assert retrieved.available is True


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
