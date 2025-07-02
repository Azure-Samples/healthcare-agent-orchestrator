# Evaluation Module: Simulate & Score Agent Conversations

This standalone module located in `/src/eval` directory enables structured simulation and evaluation of multi-agent chat systems. It is designed for testing AI agents, especially in clinical or healthcare workflows, using synthetic conversations and modular evaluation metrics.

The module supports both:
- **Reference-based evaluation** (e.g., ROUGE)
- **LLM-as-a-judge evaluation**, when gold answers are unavailable or expensive to produce

---

## Installation

This module is standalone and does **not** need to be deployed with your main agent application. To install, run the following command from `/src/`.

```bash
pip install -r requirements-eval.txt
```

This is also necessary for running the [evaluation notebook](/notebooks/evaluations/evaluation.ipynb).

> [!NOTE]
> To run Jupyter notebooks in this dev container, ensure Jupyter is installed (`pip install jupyter`) or use the VS Code Jupyter extension which is included in the dev container for running notebooks directly in VS Code.

## Quick Start

### Simulate Conversations

All simulated conversations results are saved to user-defined paths. Set them up like this:

```python
INITIAL_QUERIES_CSV_PATH = "./evaluation_sample_initial_queries.csv"
SIMULATION_OUTPUT_PATH = "./simulated_chats/patient_4"
```

To bring your own patient data and ask questions, follow the instructions in the [Data Ingestion](./data_ingestion.md). We also provide sample input queries in `./evaluation_sample_initial_queries.csv`, which you can use to directly test questions with the agent. 
Use the ChatSimulator class to create synthetic conversations with either scripted (e.g.: `ProceedUser`) or LLM-powered (e.g.: `LLMUser`) simulated users:

```python
from evaluation.chat_simulator import LLMUser, ChatSimulator

user = LLMUser()

chat_simulator = ChatSimulator(
    simulated_user=user,
    group_chat_kwargs={
        "all_agents_config": agent_config,
        "data_access": data_access,
    },
    group_followups=False,
    trial_count=1,
    max_turns=10,
    output_folder_path=SIMULATION_OUTPUT_PATH,
    save_readable_history=True,
    raise_errors=True,
)

chat_simulator.load_initial_queries(
    csv_file_path=INITIAL_QUERIES_CSV_PATH,
    patients_id_column="Patient ID",
    initial_queries_column="Initial Query",
    followup_column="Possible Follow up",
)

await chat_simulator.simulate_chats()
```

For an example of initializing `agent_config` and `data_access`, check the [evaluation](/notebooks/evaluations/evaluation.ipynb) or the [end-to-end](/notebooks/end_to_end_run.ipynb) notebooks.

Each run creates .json chat files (and if `save_readable_history` is `True`, human-readable .txt files) in the output folder. These files serve as input for evaluation.

You may also pass patient IDs, queries, and follow-up questions directly to the constructor for one-off simulations.

#### Simulate a One-Off Conversation
Instead of loading from CSV, you can pass a single patient ID, query, and follow-ups directly to the constructor:

```python
from evaluation.chat_simulator import LLMUser, ChatSimulator

patient_id = "patient_4"
initial_query = "Orchestrator: Prepare tumor board for Patient ID: patient_4"
# At least an empty string must be given as a followup question
followup_questions = ["What are the key pathology findings?"]

user = LLMUser()

chat_simulator = ChatSimulator(
    simulated_user=user,
    group_chat_kwargs={
        "all_agents_config": agent_config,
        "data_access": data_access,
    },
    patients_id=[patient_id],
    initial_queries=[initial_query],
    followup_questions=[followup_questions],
)

await chat_simulator.simulate_chats()
```

#### Chat Simulation Output
Chat simulation generates detailed records of user/agent interactions:

- Each conversation is saved as `chat_context_trial{trial}_{conversation_id}.json`
- If save_readable_history=True, a human-readable .txt version is also saved
- All files are stored in your `SIMULATION_OUTPUT_PATH`

This is handled by the following code in `simulate_chats()`:

```python
self.save(f"chat_context_trial{trial}_{checkpoint_key}.json",
          save_readable_history=self.save_readable_history)
```

### Evaluate Conversations

Once chats are [simulated or collected from real user sessions](#real-vs-simulated-conversations), use the Evaluator class to score conversations.

Just like simulated conversations, evaluation results are saved to user-defined paths. For reference-based metrics such as ROUGE, we also provide sample synthetic patient data:

```python
EVALUATION_RESULTS_PATH = os.path.join(SIMULATION_OUTPUT_PATH, "evaluation_results")
PATIENT_TIMELINE_REFERENCE_PATH = "./references/"
```

We may reuse the paths across both simulation and evaluation stages for consistent file organization.

For more information about providing reference data, check [How to Provide Reference Data](#how-to-provide-reference-data)

#### Example: ROUGE Metric
```python
from evaluation.evaluator import Evaluator
from evaluation.metrics.rouge import RougeMetric

rouge_metric = RougeMetric(
    agent_name="PatientHistory",
    reference_dir_path=PATIENT_TIMELINE_REFERENCE_PATH,
)

evaluator = Evaluator(
    metrics=[rouge_metric],
    output_folder_path=SIMULATION_OUTPUT_PATH,
)

evaluator.load_chat_contexts(SIMULATION_OUTPUT_PATH)
await evaluator.evaluate()
```

You can also skip load_chat_contexts() and pass them directly:

```python
evaluator = Evaluator(
    chats_contexts=chats_contexts,
    metrics=[rouge_metric],
    output_folder_path=SIMULATION_OUTPUT_PATH,
)

await evaluator.evaluate()
```

#### Example: LLM-Based Metric
```python
from semantic_kernel.connectors.ai.open_ai.services.azure_chat_completion import AzureChatCompletion
from evaluation.metrics.agent_selection import AgentSelectionEvaluator

llm_service = AzureChatCompletion(
    deployment_name=os.environ["AZURE_OPENAI_DEPLOYMENT_NAME"],
    api_version="2024-12-01-preview",
    endpoint=os.environ["AZURE_OPENAI_ENDPOINT"],
)

agent_selection_evaluator = AgentSelectionEvaluator(
    evaluation_llm_service=llm_service,
)

evaluator = Evaluator(
    metrics=[agent_selection_evaluator],
    output_folder_path=SIMULATION_OUTPUT_PATH,
)

evaluator.load_chat_contexts(SIMULATION_OUTPUT_PATH)
await evaluator.evaluate()
```

For more information about the evaluation output check [Evaluation output](#evaluation-output)

#### Available Evaluation Metrics

##### LLM-as-Judge Metrics
- AgentSelectionEvaluator – Did the orchestrator pick the right agent?
- InformationAggregationEvaluator – Was info synthesized across sources?

These rely on LLMs (e.g., Azure OpenAI) and can be configured using the evaluator’s evaluation_llm_service parameter.

LLM metrics are powerful but non-deterministic. Use them alongside reference-based metrics or human review when possible.

######  LLM Evaluation: Known Issues
LLM-as-a-judge evaluation offers flexibility in assessing complex agent behavior—but it's not without limitations:

**Known Issues**
Model Connectivity: In rare cases, the evaluator LLM may fail to return a response due to API timeouts or service issues.

Non-Determinism: LLM outputs may vary between runs. For critical evaluation, pair LLM metrics with reference-based methods or human spot-checking.

Bias and low reproducibility: Changing the underlying LLM or prompts may drastically change the absolute scores that are returned.

> ❗**Note:** Especially for LLM-based metrics, avoid interpreting results from their absolute value. Due to the subjective nature of these metrics, it's more reliable to compare the change in these metrics from two different versions.

##### Reference-Based Metric
In addition to LLM-as-a-judge metrics, this module supports reference-based evaluation, such as ROUGE, for use cases where a trusted ground truth exists.

- ROUGE (RougeMetric) – Standard lexical overlap scoring, useful when gold references exist.

###### How to Provide Reference Data
Each reference response should be saved as a .txt file in a designated directory. File names must match the patient_id used in simulation.

Example directory structure:
```
/references/
├── patient_7.txt
├── patient_8.txt
```

Each file should contain the expected agent response (e.g., patient summary from the PatientHistory agent) in plain text.

###### Usage Example
Initialize the metric:

```python
from evaluation.metrics.rouge import RougeMetric

rouge_metric = RougeMetric(
    agent_name="PatientHistory", 
    reference_dir_path="../data/references"
)
```

Once initialized, pass rouge_metric to your Evaluator:

```python
from evaluation.evaluator import Evaluator

evaluator = Evaluator(
    metrics=[rouge_metric],
    output_folder_path="../data/simulated_chats/patient_4/evaluation_results"
)

evaluator.load_chat_contexts("../data/simulated_chats/patient_4")
await evaluator.evaluate()
```

If reference files are missing or the agent response is not found, the metric will report an error with score: 0

#### Real vs Simulated Conversations
You can evaluate either:

##### Real conversations

Real conversations, captured from actual deployment use.

The chat sessions are automatically saved whenever a conversation is terminated with the command `@Orchestrator: clear`. These saved conversations can be loaded directly for evaluation using the Evaluator class. This provides a convenient way to assess real-world performance without additional setup. 

##### Simulated conversations

Generated offline with the ChatSimulator, useful for prototyping or regression testing.

This mode produce compatible .json output files that can be evaluated using the same Evaluator interface. For more information see [Simulate conversations](#simulate-conversations).

#### Evaluation Output
Evaluation metrics generate a single JSON at the end of each run: `summary_<timestamp>.json` with results for all metrics

All evaluation files are saved to the path given to `Evaluator.output_folder_path`.

Example result:
```json
{
  "timestamp": "20250507_120422",
  "metrics": {
    "rouge": {
      "average_score": 0.1501,
      "num_evaluations": 6,
      "num_errors": 0,
      "results": [
        {
          "id": "...",
          "patient_id": "patient_4",
          "results": {
            "score": 0.10640870616686819,
            "explanation": "ROUGE-1: 0.281, ROUGE-2: 0.073, ROUGE-L: 0.106",
            "details": {
              "patient_id": "patient_4",
              "reference": "...",
              "reference_length": 1374,
              "agent_response": "...",
              "agent_response_length": 4687,
              "rouge1": 0.28053204353083433,
              "rouge2": 0.07272727272727272,
              "rougeL": 0.10640870616686819
            }
          }
        },
        ...
      ]
    },
    "PatientHistory_tbfact": {
      "average_score": 0.26316768327641993,
      "num_evaluations": 6,
      "num_errors": 0,
      "results": [
        {
            "id": "...",
            "patient_id": "patient_4",
            "result": {
                "score": 0.4444444444444444,
                "explanation": "Precision: 0.333, Recall: 0.667, F1: 0.444",
                "details": {
                "patient_id": "patient_4",
                "reference": "...",
                "agent_response": "...",
                "metrics": {
                    "precision": 0.3333333333333333,
                    "recall": 0.6666666666666666,
                    "f1": 0.4444444444444444,
                    "precision_support": 12,
                    "recall_support": 21
                },
                "category_metrics": {},
                "fact_evaluations": []
            }
          }
        }
      ]
    }
  }
}
```

Each metric output should follow the same schema:
```json
{
      "average_score": 0.26316768327641993,
      "num_evaluations": 6,
      "num_errors": 0,
      "results": []
}
```

In turn, `results` should be a list of objects with `score`, `explanation` and `details` keys. Under `details` we may add any additional data specific for that metric.

## Extending the Framework

### Adding New Metrics

The framework provides several base classes to make building new evaluation metrics easier. For consistency, new metrics should inherit from one of these base classes, all of which trace back to `EvaluationMetric`.

Each base class handles common functionality such as processing chat histories, extracting agent-specific responses or loading and comparing reference data:

- **`EvaluationMetric`**: The core abstract class all metrics inherit from.
- **`AgentEvaluationMetric`**: For evaluating specific agents' responses, handles filtering chat history.
- **`ReferenceBasedMetric`**: For metrics that use ground truth/reference data. By design this is an `AgentEvaluationMetric`
- **`LLMasJudge`**: For metrics that use LLMs to evaluate responses
- **`AgentLLMasJudge`**: Combines agent evaluation with LLM judgment
- **`AgentReferenceBasedLLMasJudge`**: Combines agent evaluation, reference data, and LLM judgment

To create a new metric:
1. Choose the appropriate base class based on your needs
2. Implement the required abstract methods
3. Register your metric with the Evaluator

As an example, see how we can implement an LLM-based metric:

```python
from evaluation.metrics.base import LLMasJudge
from semantic_kernel.connectors.ai.open_ai.services.azure_chat_completion import AzureChatCompletion

class MyLLMEvaluator(LLMasJudge):
    @property
    def name(self) -> str:
        return "my_llm_metric"

    @property
    def description(self) -> str:
        return "LLM evaluation based on XYZ criteria"

    @property
    def min_score(self) -> int:
        return 1

    @property
    def max_score(self) -> int:
        return 5

    @property
    def system_prompt(self) -> str:
        return """You are an expert AI evaluator. Rate the quality of this response on a scale from 1 (poor) to 5 (excellent). Start with 'Rating: X'."""

    def process_rating(self, content: str) -> int:
        return self.default_rating_extraction(content)
```

Usage:

```python
llm_service = AzureChatCompletion(
    deployment_name="...",
    api_version="...",
    endpoint="..."
)

evaluator = Evaluator(
    metrics=[MyLLMEvaluator(evaluation_llm_service=llm_service)],
    output_folder_path="evaluation_results/"
)
```

> Tip: You can view and update the evaluation prompts in `/src/evaluation/metrics/`.

### Add a New Simulated User

1. **Implement the `SimulatedUserProtocol`**  
   This defines how your simulated user behaves during the conversation.

2. **Create a user class**  
   You can start by extending the built-in examples:  
   - `ProceedUser`: rule-based, always responds with “proceed” or the next follow-up  
   - `LLMUser`: generates dynamic follow-up messages using a language model

3. **Pass your user into the `ChatSimulator`**  
   *Example:*

   ```python
   from evaluation.chat_simulator import LLMUser, ChatSimulator

   user = LLMUser()

   chat_simulator = ChatSimulator(
       simulated_user=user,
       group_chat_kwargs={
           "all_agents_config": agent_config,
           "data_access": data_access,
       },
       patients_id=["patient_4"],
       initial_queries=["Orchestrator: Prepare tumor board for Patient ID: patient_4"],
       followup_questions=[[""]],
       trial_count=1,
       max_turns=10,
       output_folder_path=SIMULATION_OUTPUT_PATH,
       save_readable_history=True,
   )
   await chat_simulator.simulate_chats()

## Where to Go After Evaluation

Once you've reviewed your evaluation results, here are common next steps to iterate on performance:

> 💡 Tip: Manually checking some of the conversations can give better insight into common problems with the application.

### 1. Modify the Initial Query
Having an idea of what pitfalls the application have allow you to modify your test cases to make sure you constantly verify performance of problematic areas:

- Refine the initial query
- Add new follow-up questions
- Adjust the patient context

All of this can be done by updating your input CSV (`INITIAL_QUERIES_CSV_PATH`) or directly supplying inputs in code.

### 2. Update Agent Instructions or Tools
To improve agent behavior:

- Edit agent instructions in `/src/scenarios/default/config/agents.yaml`.
- Add or modify tools under `/src/scenarios/default/tools/`.

These changes will impact how agents respond in future simulations.

### 3. Refining evaluation process

After improving/fixing the application, consider adding test cases or additional metrics to help monitor the performance on those specifics aspects.

Also, consider including human annotations for testing specific behaviour and for understanding how the existing metrics (or the new ones you added) correlate to human experts.