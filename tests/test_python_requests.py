def test_request_items_runner_fixture(testdir):
    """Make sure that pytest accepts our fixture."""

    # create a temporary pytest test module
    testdir.makepyfile(
        """
        def test_exists(request_items_runner):
            assert request_items_runner
    """
    )

    # run pytest with the following cmd args
    result = testdir.runpytest("-v")

    # fnmatch_lines does an assertion internally
    result.stdout.fnmatch_lines(["*::test_exists PASSED*"])

    # make sure that that we get a '0' exit code for the testsuite
    assert result.ret == 0


def test_help_message(testdir):
    result = testdir.runpytest("--help")

    # fnmatch_lines does an assertion internally
    result.stdout.fnmatch_lines(["requests:", "*--requests-baseurl*"])
    result.stdout.fnmatch_lines(["requests:", "*--requests-timeout*"])
    result.stdout.fnmatch_lines(["requests:", "*--requests-extra-vars*"])
