# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

"""
Evaluation module for assessing chat interactions.

Usage:
    evaluator = Evaluator()
    evaluator.load_chat_contexts("path/to/chats")
    evaluator.setup_metrics([metric1, metric2])
    results = await evaluator.evaluate()
"""

import json
import logging
import os
import traceback
from datetime import datetime
from typing import Any

from data_models.chat_context import ChatContext
from data_models.chat_context_accessor import ChatContextAccessor

from .metrics.base import EvaluationMetric


class Evaluator:
    """
    Evaluates chat interactions using configurable metrics.

    Attributes:
        chat_contexts: List of chat contexts to be evaluated
        metrics: List of evaluation metrics to apply
        output_folder_path: Directory where evaluation results will be saved
    """

    def __init__(
        self,
        chats_contexts: list[ChatContext] = None,
        metrics: list[EvaluationMetric] = None,
        output_folder_path: str = "evaluation_runs",
    ):
        """
        Initialize the Evaluator with optional contexts, metrics, and output path.

        Args:
            chats_contexts: Optional list of ChatContext instances to evaluate
            metrics: Optional list of EvaluationMetric instances to apply
            output_folder_path: Directory path for saving evaluation results
                                (created if it doesn't exist)
        """
        self.chat_contexts: list[ChatContext] = []
        if chats_contexts:
            self.chat_contexts.extend(chats_contexts)

        self.metrics: list[EvaluationMetric] = []
        if metrics:
            self.setup_metrics(metrics)

        self.output_folder_path = output_folder_path
        os.makedirs(self.output_folder_path, exist_ok=True)

    def setup_metrics(self, metrics: list[EvaluationMetric]):
        """
        Set up evaluation metrics for the evaluator.

        Args:
            metrics: A list of EvaluationMetric instances to be used for evaluation

        Returns:
            self: Returns the instance for method chaining
        """
        self.metrics.extend(metrics)
        logging.info(f"Added {len(metrics)} evaluation metrics: {', '.join(metric.name for metric in metrics)}")

        return self  # Return self for method chaining

    def add_chat_contexts(self, chat_contexts: list[ChatContext]):
        """
        Add chat contexts for evaluation.

        Args:
            chat_contexts: A list of ChatContext instances to be added for evaluation.

        Returns:
            self: Returns the instance for method chaining
        """
        self.chat_contexts.extend(chat_contexts)
        logging.info(f"Added {len(chat_contexts)} chat contexts for evaluation")

        return self

    def load_chat_contexts(self, folder_path: str, extend: bool = True):
        """
        Load chat contexts from a folder.

        Args:
            folder_path: The path to the folder containing chat context files.
            extend: Whether to extend the existing chat contexts or replace them.

        Returns:
            self: Returns the instance for method chaining
        """
        if not os.path.exists(folder_path):
            logging.error(f"Folder {folder_path} does not exist.")
            return

        chat_contexts: list[ChatContext] = []
        chat_files = [f for f in os.listdir(folder_path) if f.endswith(".json")]
        for chat_file in chat_files:
            file_path = os.path.join(folder_path, chat_file)
            try:
                with open(file_path, 'r') as f:
                    chat_context_str = f.read()
                    chat_contexts.append(ChatContextAccessor.deserialize(chat_context_str))
            except Exception as e:
                logging.error(f"Error reading chat file {chat_file}: {e}")

        logging.info(f"Loaded {len(chat_contexts)} chat contexts from {folder_path}")

        if extend:
            self.chat_contexts.extend(chat_contexts)
        else:
            self.chat_contexts = chat_contexts

        return self

    async def evaluate(self) -> dict[str, Any]:
        """
        Evaluate all simulated chats using all configured metrics.

        Returns:
            A dictionary mapping metric names to their evaluation results
        """
        if not self.metrics:
            logging.warning("No evaluation metrics configured. Call setup_metrics() first.")
            return {}

        if not self.chat_contexts:
            logging.warning(
                "No chat contexts available for evaluation. Call add_chat_contexts() or load_chat_contexts() first.")
            return {}

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

        results = {}
        for metric in self.metrics:
            logging.info(f"Running evaluation with metric: {metric.name}")
            metric_results = await self._evaluate(metric, self.chat_contexts)
            results[metric.name] = metric_results

        # Create an overall summary file
        summary = {
            "timestamp": timestamp,
            "metrics": {}
        }

        for metric_name, metric_results in results.items():
            # Extract valid scores handling nested result structures
            valid_scores = []
            for result in metric_results:
                score = None
                # Handle different result structures
                if "result" in result:
                    if isinstance(result["result"], dict):
                        if "score" in result["result"]:
                            score = result["result"]["score"]
                        elif "result" in result["result"] and "score" in result["result"]["result"]:
                            score = result["result"]["result"]["score"]
                
                # Add valid positive scores
                if score is not None and score > 0:
                    valid_scores.append(score)

            # Calculate metrics
            avg_score = sum(valid_scores) / len(valid_scores) if valid_scores else 0
            num_valid = len(valid_scores)
            num_total = len(metric_results)
            num_errors = num_total - num_valid

            logging.info(f"Metric {metric_name}: {num_valid} valid scores out of {num_total} total evaluations")
            
            summary["metrics"][metric_name] = {
                "average_score": avg_score,
                "num_evaluations": num_valid,
                "num_errors": num_errors,
                "results": metric_results
            }

        summary_file = os.path.join(self.output_folder_path, f"summary_{timestamp}.json")
        with open(summary_file, 'w') as f:
            json.dump(summary, f, indent=2)

        logging.info(f"Overall evaluation summary saved to {summary_file}")
        return summary

    # The existing evaluate method remains unchanged
    async def _evaluate(self, metric: EvaluationMetric, chat_contexts: list[ChatContext]) -> list[dict[str, Any]]:
        """
        Evaluate all simulated chats using the provided metric.

        Args:
            metric: The evaluation metric to use

        Returns:
            A list of evaluation results, each containing the chat file path, score, and explanation
        """
        results = []

        for context in chat_contexts:
            patient_id = context.patient_id if hasattr(context, "patient_id") else None

            # Evaluate the chat history
            try:
                evaluation_results = await metric.evaluate(
                    chat_history=context.chat_history,
                    patient_id=patient_id
                )

                for eval_result in evaluation_results:
                    results.append({
                        "id": context.conversation_id,
                        "patient_id": patient_id,
                        "result": eval_result,
                    })

            except Exception as e:
                error_traceback = traceback.format_exc()
                logging.error(f"Error evaluating {context.conversation_id}: {e}\n{error_traceback}")
                results.append({
                    "id": context.conversation_id,
                    "patient_id": patient_id,
                    "result": {
                        "error": str(e),
                        "trace": error_traceback,
                    },
                })

        return results
