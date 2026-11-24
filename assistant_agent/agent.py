
# ----------------------------------
# STATUS REPORT BUILDER
# ----------------------------------

def build_status_report_for_user(user_id: str) -> dict:
    """
    Build a professionally formatted daily status report
    using only the specified user's tasks.
    """

    today = datetime.now(TIMEZONE).date()
    today_string = today.isoformat()
    display_date = today.strftime("%d %B %Y")

    try:
        tasks = list(
            tasks_collection.find(
                {
                    "user_id": str(user_id),
                    "date": today_string
                },
                {"_id": 0}
            ).sort("created_at", 1)
        )

        completed_tasks = [
            task for task in tasks
            if task.get("status") == "completed"
        ]

        pending_tasks = [
            task for task in tasks
            if task.get("status") == "pending"
        ]

        report_lines = [
            f"TASK COMPLETED – {display_date}",
            ""
        ]

        # Completed tasks
        if completed_tasks:

            for index, task in enumerate(completed_tasks, start=1):

                description = task.get(
                    "task", "Untitled task"
                ).strip()

                # Separate title and description if a colon exists
                if ":" in description:
                    title, details = description.split(":", 1)

                    report_lines.append(
                        f"{index}. {title.strip()}: "
                        f"{details.strip().rstrip('.')}."
                    )

                else:
                    report_lines.append(
                        f"{index}. {description.rstrip('.')}."
                    )

                report_lines.append("")

        else:
            report_lines.append(
                "No tasks have been marked completed today."
            )

        # Pending tasks
        if pending_tasks:

            report_lines.extend([
                "PENDING TASKS",
                ""
            ])

            for index, task in enumerate(pending_tasks, start=1):

                description = task.get(
                    "task", "Untitled task"
                ).strip()

                report_lines.append(
                    f"{index}. {description.rstrip('.')}."
                )

        report = "\n".join(report_lines).strip()

        return {
            "status": "success",
            "user_id": str(user_id),
            "date": today_string,
            "report": report,
            "total_tasks": len(tasks),
            "completed_tasks": len(completed_tasks),
            "pending_tasks": len(pending_tasks)
        }

    except Exception as error:
        return {
            "status": "error",
            "message": f"Failed to generate report: {str(error)}"
        }
