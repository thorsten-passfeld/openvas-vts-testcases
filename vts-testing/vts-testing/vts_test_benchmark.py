import os
import sys
import re
import argparse
import random
import time

from pathlib import Path
from unittest.mock import patch

from tqdm import tqdm, trange

from .funcs import get_all_test_cases_in_dir
from .vts_test import main as vts_test_main_func

TEST_CASE_PATH_PATTERN = re.compile(r"(/test_cases/.*)")


def get_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="VTs Testing Benchmark")

    parser.add_argument(
        type=str,
        dest="test_cases_base_dir",
        help=("base path to the test case(s) for deploying emulated services."),
    )
    parser.add_argument(
        "-i",
        "--benchmark-id",
        type=int,
        dest="benchmark_id",
        default=1,
        help="the ID of the benchmark to run.",
    )
    args = parser.parse_args()
    return args


def save_results_to_file(file_name: str, scan_times_seconds: list) -> None:
    base_dir_name = "benchmark_results"
    output_file_path = f"{base_dir_name}/{file_name}.txt"
    Path(base_dir_name).mkdir(parents=False, exist_ok=True)
    with open(output_file_path, "w", encoding="utf-8") as output_file:
        for scan_time in scan_times_seconds:
            output_file.write(f"{scan_time}\n")
    tqdm.write(f"Wrote benchmark results to {output_file_path}")


def run_test(test_cases: list, num_scans: int = 1) -> float:
    # Using the time module in Python around calling vts_test_main_func()
    # Manually set the cli args so that the main function can parse them
    # Because vts_test.py recognizes when we supply the test case path on the command line
    vts_test_argv = ["vts-test"]
    vts_test_argv.extend(test_cases)
    vts_test_argv.extend(["--num-scans", str(num_scans)])

    with patch.object(sys, "argv", vts_test_argv):
        sys.stdout = open(os.devnull, "w", encoding="utf-8")
        sys.stderr = open(os.devnull, "w", encoding="utf-8")
        before_seconds = time.perf_counter()
        vts_test_main_func()
        real_time_seconds = time.perf_counter() - before_seconds
        sys.stdout = sys.__stdout__
        sys.stderr = sys.__stderr__
    return real_time_seconds


def generate_random_samples_of_test_cases(
    num_runs: int, num_test_cases: int, all_test_cases: list
) -> list:
    sampled_test_cases_for_all_runs = list()
    while len(sampled_test_cases_for_all_runs) < num_runs:
        # Try generating a unique sequence of test cases
        sorted_sample = sorted(random.sample(all_test_cases, num_test_cases))
        # Only add it if it's unique. Otherwise generate a new sample
        if sorted_sample not in sampled_test_cases_for_all_runs:
            sampled_test_cases_for_all_runs.append(sorted_sample)
    return sampled_test_cases_for_all_runs


def run_benchmark_num_test_cases(test_cases_base_dir: Path):
    numbers_of_test_cases_to_test = [1, 10, 20, 30, 40, 50, 60, 70, 80, 90, 100, 110, 120]
    num_runs = 50
    all_test_cases = get_all_test_cases_in_dir(test_cases_base_dir)

    for num_test_cases_to_test in tqdm(numbers_of_test_cases_to_test):
        if num_test_cases_to_test == len(all_test_cases):
            sampled_test_cases_for_all_runs = [all_test_cases] * num_runs
        else:
            sampled_test_cases_for_all_runs = generate_random_samples_of_test_cases(
                num_runs, num_test_cases_to_test, all_test_cases
            )
        test_times_seconds = list()
        for test_cases in tqdm(sampled_test_cases_for_all_runs):
            test_time_seconds = run_test(test_cases, num_scans=1)
            tqdm.write(f"{test_time_seconds} seconds")
            test_times_seconds.append(test_time_seconds)

        output_file_name = f"test_with_{num_test_cases_to_test}_test_cases"
        save_results_to_file(output_file_name, test_times_seconds)


def run_benchmark_num_concurrent_scans(test_cases_base_dir: Path):
    num_runs = 100
    all_test_cases = get_all_test_cases_in_dir(test_cases_base_dir)

    for num_concurrent_scans in trange(1, os.cpu_count() + 1):
        tqdm.write(f"Benchmarking with {num_concurrent_scans} concurrent scans...")
        test_times_seconds = list()
        for _ in trange(num_runs):
            test_time_seconds = run_test(all_test_cases, num_scans=num_concurrent_scans)
            tqdm.write(f"{test_time_seconds} seconds")
            test_times_seconds.append(test_time_seconds)

        output_file_name = f"{num_concurrent_scans}_concurrent_scans"
        save_results_to_file(output_file_name, test_times_seconds)


def main():
    args = get_args()
    test_cases_base_dir = args.test_cases_base_dir
    if not os.path.isdir(test_cases_base_dir):
        exit(f"Test case base path '{test_cases_base_dir}' does not exist!")
    else:
        test_cases_base_dir = Path(test_cases_base_dir)
    benchmark_id = args.benchmark_id

    if benchmark_id == 1:
        run_benchmark_num_test_cases(test_cases_base_dir)
    elif benchmark_id == 2:
        run_benchmark_num_concurrent_scans(test_cases_base_dir)
    else:
        exit(f"Error: No benchmark has the id {benchmark_id}")


if __name__ == "__main__":
    main()
