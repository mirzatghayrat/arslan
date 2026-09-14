from evals.companion.scoring import task_cluster_interval


def test_interval_resamples_tasks_not_individual_attempts():
    result = task_cluster_interval([0, 1], samples=1000)
    assert result["task_clusters"] == 2
    assert result["lower"] == 0 and result["upper"] == 1
    assert result == task_cluster_interval([0, 1], samples=1000)


def test_interval_is_not_claimed_for_one_task():
    assert task_cluster_interval([1]) is None


def test_all_passes_is_degenerate_but_explicitly_small_catalog():
    assert task_cluster_interval([1] * 30)["lower"] == 1
