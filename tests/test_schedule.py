from hotin import schedule


def test_cron_line_daily_and_twice():
    assert schedule.cron_line("daily", "/py") == "0 8 * * * /py -m hotin refresh --quiet # hotin-managed"
    assert schedule.cron_line("twice", "/py").startswith("0 8,20 * * * /py -m hotin refresh --quiet")


def test_merged_crontab_replaces_our_block_and_preserves_user_lines():
    user = "0 5 * * * backup.sh"
    once = schedule.merged_crontab(user, "daily", "/py")
    assert user in once and once.count("# hotin-managed") == 1

    # re-installing at a new frequency replaces, never stacks
    twice = schedule.merged_crontab(once, "twice", "/py")
    assert twice.count("# hotin-managed") == 1 and "0 8,20" in twice and user in twice

    # turning it off leaves only the user's own line
    assert schedule.merged_crontab(twice, None, "/py").strip() == user


def test_merged_crontab_empty_when_no_user_lines_and_off():
    installed = schedule.merged_crontab("", "daily", "/py")
    assert schedule.merged_crontab(installed, None, "/py") == ""


def test_task_specs_windows_names_and_times():
    assert schedule.task_specs("twice", "/py") == [
        ("hotin-ingest-0800", "08:00"),
        ("hotin-ingest-2000", "20:00"),
    ]


def test_demo_runs():
    schedule.demo()
