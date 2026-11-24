from codag.core.router import SkillRouter


def test_router_fast_path_files():
    router = SkillRouter()
    assert router.route_fast_path("create file report.txt") == "files"
    assert router.route_fast_path("read file README.md") == "files"
    assert router.route_fast_path("delete file old.tmp") == "files"


def test_router_fast_path_shell():
    router = SkillRouter()
    assert router.route_fast_path("run git status in terminal") == "shell"
    assert router.route_fast_path("run command pytest") == "shell"


def test_router_fast_path_tasks():
    router = SkillRouter()
    assert router.route_fast_path("add a task to buy milk") == "tasks"
    assert router.route_fast_path("list my pending tasks") == "tasks"
    assert router.route_fast_path("mark task #2 as completed") == "tasks"


def test_router_fast_path_notes():
    router = SkillRouter()
    assert router.route_fast_path("create a note titled meeting") == "notes"
    assert router.route_fast_path("search notes for budget") == "notes"
    assert router.route_fast_path("list all my notes") == "notes"


def test_router_fast_path_code():
    router = SkillRouter()
    assert router.route_fast_path("build a small CLI todo app") == "code"
    assert router.route_fast_path("plan project for a microservice") == "code"
    assert router.route_fast_path("write code for a new feature") == "code"


def test_router_plain_conversation():
    router = SkillRouter()
    assert router.route("hello there") is None
    assert router.route("what is the speed of light?") is None
    assert router.route("how are you") is None
