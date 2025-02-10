import shutil
from collections.abc import Callable, Sequence
from pathlib import Path
from PIL import Image
from multiprocessing import Pool, Manager, cpu_count


def optimize_img_to_png(image_in: Path, output_dir: Path) -> Path:
    """Converts an image to PNG and optimizes it, saving it in the output directory."""
    output_path = output_dir / image_in.with_suffix(".png").name
    image = Image.open(image_in)
    image.save(output_path, "PNG", optimize=True)
    return output_path


class MultiProcessImageOptimizer:
    def __init__(
        self,
        max_workers: int | None = None,
        batch_size: int = 4,
        on_job_done: Callable[[Path, int, int], None] | None = None,
        on_all_jobs_done: Callable[[], None] | None = None,
        cpu_fraction: float = 0.25,
    ):
        """Initialize the customizable pool executor."""
        self.max_workers = max_workers or self._get_optimize_workers(cpu_fraction)
        self.batch_size = batch_size
        self.on_job_done = on_job_done
        self.on_all_jobs_done = on_all_jobs_done

    def _job_callback(self, result, completed_jobs, total_jobs, lock):
        """Updates progress after a job completes."""
        with lock:
            completed_jobs.value += 1
            if self.on_job_done:
                self.on_job_done(result, completed_jobs.value, total_jobs)

    def _process_batch(
        self,
        job_batch: Sequence[Path],
        output_dir: Path,
        completed_jobs,
        total_jobs: int,
        lock,
    ):
        """Process a batch of jobs concurrently using multiprocessing."""
        with Pool(self.max_workers) as pool:
            for in_path in job_batch:
                pool.apply_async(
                    optimize_img_to_png,
                    (in_path, output_dir),
                    callback=lambda res: self._job_callback(
                        res, completed_jobs, total_jobs, lock
                    ),
                )

            pool.close()
            pool.join()

    def process_jobs(
        self, input_files: Sequence[Path], output_dir: Path
    ) -> Sequence[Path]:
        """Process a sequence of input files and save results in output_dir."""
        total_jobs = len(input_files)

        if output_dir.exists():
            shutil.rmtree(output_dir)
        output_dir.mkdir(exist_ok=True, parents=True)

        with Manager() as manager:
            completed_jobs = manager.Value("i", 0)
            lock = manager.Lock()

            job_batches = [
                input_files[i : i + self.batch_size]
                for i in range(0, len(input_files), self.batch_size)
            ]

            for batch in job_batches:
                self._process_batch(batch, output_dir, completed_jobs, total_jobs, lock)

            # callback when all jobs are done
            if self.on_all_jobs_done:
                self.on_all_jobs_done()

        return [x for x in output_dir.glob("*")]

    @staticmethod
    def _get_optimize_workers(fraction: float = 0.25) -> int:
        total_cores = cpu_count() or 2
        return max(1, int(total_cores * fraction))


if __name__ == "__main__":
    jpg_in_dir = Path(r"")
    png_out_dir = Path(r"")

    # collect input files
    input_files = [
        x for x in jpg_in_dir.glob("*") if x.suffix.lower() in {".jpg", ".jpeg", ".png"}
    ]

    # callbacks
    def job_done_callback(png_path: Path, completed: int, total: int):
        print(f"✔ {completed}/{total} - Job completed: {png_path}")

    def all_jobs_done_callback():
        print("🎉 All jobs completed!")

    optimizer = MultiProcessImageOptimizer(
        batch_size=4,
        on_job_done=job_done_callback,
        on_all_jobs_done=all_jobs_done_callback,
        cpu_fraction=0.5,
    )

    optimizer.process_jobs(input_files, png_out_dir)
