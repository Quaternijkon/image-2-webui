from app.core.config import AppConfig
from app.core.file_scanner import scan_input_images
from app.core.models import InputImage, JobLayout, PlannedJob, TaskPlan
from app.core.output_planner import OutputPlanner
from app.core.prompt_renderer import PromptRenderer


class TaskPlanner:
    def __init__(self, config: AppConfig) -> None:
        self.config = config

    def build(self) -> PlannedJob:
        output_planner = OutputPlanner(self.config)
        if self.config.input.mode == "generate":
            tasks = self._build_generate_tasks_without_outputs()
            job = output_planner.create_job_layout()
            self._assign_outputs(tasks, output_planner, job)
            return PlannedJob(job=job, tasks=tasks, issues=[])

        scan = scan_input_images(self.config.input)
        tasks = self._build_image_tasks_without_outputs(scan.images)
        job = output_planner.create_job_layout()
        self._assign_outputs(tasks, output_planner, job)
        return PlannedJob(job=job, tasks=tasks, issues=scan.issues)

    def _build_generate_tasks_without_outputs(self) -> list[TaskPlan]:
        tasks: list[TaskPlan] = []
        for index in range(1, self.config.image.n + 1):
            task_id = f"{index:06d}"
            prompt = self._render_prompt(
                stem="generate",
                index=task_id,
                variant=f"v{index}",
            )
            task = TaskPlan(
                task_id=task_id,
                mode="generate",
                source_paths=[],
                mask_path=None,
                rendered_prompt=prompt,
                variant=index,
                output_plan=None,
            )
            tasks.append(task)
        return tasks

    def _build_image_tasks_without_outputs(self, images: list[InputImage]) -> list[TaskPlan]:
        tasks: list[TaskPlan] = []
        task_number = 1
        for image in images:
            for variant in range(1, self.config.image.n + 1):
                task_id = f"{task_number:06d}"
                prompt = self._render_prompt(
                    stem=image.path.stem,
                    index=task_id,
                    variant=f"v{variant}",
                )
                task = TaskPlan(
                    task_id=task_id,
                    mode=self.config.input.mode,
                    source_paths=[image.path],
                    mask_path=image.mask_path,
                    rendered_prompt=prompt,
                    variant=variant,
                    output_plan=None,
                    input_image=image,
                    status="validation_failed"
                    if image.validation_status == "validation_failed"
                    else "queued",
                )
                tasks.append(task)
                task_number += 1
        return tasks

    def _assign_outputs(
        self, tasks: list[TaskPlan], output_planner: OutputPlanner, job: JobLayout
    ) -> None:
        reserved_paths: set = set()
        for task in tasks:
            task.output_plan = output_planner.plan_variant_output(
                job,
                task,
                variant=task.variant,
                reserved_paths=reserved_paths,
            )
            reserved_paths.add(task.output_plan.final_path)

    def _render_prompt(self, *, stem: str, index: str, variant: str) -> str:
        renderer = PromptRenderer(
            variables_enabled=self.config.prompt.variables_enabled,
            context={
                "stem": stem,
                "index": index,
                "variant": variant,
                "quality": self.config.image.quality,
                "size": self.config.image.size,
                "date": "",
                "hash": "",
            },
        )
        return renderer.render(self.config.prompt.template)


__all__ = ["TaskPlanner", "PlannedJob"]
