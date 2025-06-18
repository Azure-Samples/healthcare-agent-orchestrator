# User Guide
Once deployed, all your agents are accessible in Microsoft Teams. You can interact with the Orchestrator Agent (the orchestrator) or engage with individual agents as needed.

## Send a Message in Teams

A Teams agent will only respond to a message if it contains a mention. Always start a message by mentioning the name of the agent.
- Type `@AgentName` in the chat and select an agent from the list of names.
- Type your message.
- Press Enter or click the send button.

You can start a chat using one of the following messages:
- $\color{#7b83eb}{\text{@Orchestrator}}$ prepare tumor board for patient id patient_4
- $\color{#7b83eb}{\text{@PatientHistory}}$ create patient timeline for patient id patient_4
- $\color{#7b83eb}{\text{@ClinicalTrials}}$ what trials would the following patient qualify for
  - Age: 66 years old
  - Patient Gender: Female
  - Staging: Likely stage IV disease
  - Primary Site: Lung
  - Histology: Non-small cell lung carcinoma, adenocarcinoma type
  - Biomarkers: EGFR mutation, TP53 mutation, RTK mutation
  - Treatment History:
    - Right upper lobe lobectomy in 2018
    - Chemotherapy with Carboplatin, Paclitaxel, and Keytruda
    - Maintenance Pembrolizumab
    - Currently on Osimertinib and Bevacizumab
  - ECOG Performance Status: 1

And follow up with one of the following messages:
- $\color{#7b83eb}{\text{@Orchestrator}}$ proceed with the plan
- $\color{#7b83eb}{\text{@PatientHistory}}$ can you create a table with all of the medications this patient has taken over time?
- $\color{#7b83eb}{\text{@PatientHistory}}$ can you tell me more about when chemotherapy happened relative to the KRAS mutation?

## Interaction Tips

### Clear Chat History

Restart the conversation flow by saying $\color{#7b83eb}{\text{@Orchestrator}}$ clear.

### Interrupting Long-Running Tasks

It is a known issue that long-running task orchestration may be interrupted if the user introduces another query into the Teams chat session while a task is running. For example, asking to prepare a patient timeline involves coordination between multiple agents and takes time. If a request for the PatientHistory agent to provide details of a procedure is made while the timeline request is underway, the timeline result may never come back. We recommend avoiding additional requests while a task is running.

### Action Plan Dependency on Initial Prompt

The $\color{#7b83eb}{\text{@Orchestrator}}$ agent is sensitive to the initial request. Depending on how the request is made, the orchestrator's proposed plan will vary.

Consider two requests:
1. $\color{#7b83eb}{\text{@Orchestrator}}$ _Generate a patient timeline for patient_7._
2. $\color{#7b83eb}{\text{@Orchestrator}}$ _Based on the full clinical picture of patient_7 - including stage, biomarkers, treatment response, and recent imaging - generate a comprehensive patient timeline._

The second request will result in a more comprehensive plan and a more detailed timeline, while the first one may generate a shorter version of the timeline, e.g., omitting radiological results with images.

## Configuring Research Agent

The research agent leverages [GraphRAG](https://github.com/microsoft/graphrag), a modular graph-based Retrieval-Augmented Generation (RAG) system developed by Microsoft Research. To use the research agent effectively, deploy and index your own instance of GraphRAG. The [graphrag-accelerator](https://github.com/azure-samples/graphrag-accelerator) simplifies this setup process.

### Configuration Steps

1. **Update Configuration File**  
  Specify the GraphRAG endpoint and index details in the `scenarios/default/config/agents.yaml` file:
  ```yaml
  graph_rag_url: "https://graphrag.azure-api.net/"
  graph_rag_index_name: "wiki-articles-demo-index"
  ```

2. **Set API Key Securely**  
  Use the Azure Developer CLI to securely store the API key:
  ```bash
  azd env set-secret GRAPH_RAG_SUBSCRIPTION_KEY
  ```
  Refer to the [Azure Developer CLI documentation](https://learn.microsoft.com/azure/developer/azure-developer-cli/) for detailed instructions on managing secrets.

### Technical Limitations

The research agent's performance depends on the quality of the indexed data and the configuration of the GraphRAG system. Ensure proper indexing and validation to achieve optimal results.

The Healthcare Agent Orchestration framework is not intended for direct clinical use, including diagnosis, treatment, or disease prevention. It should not replace professional medical advice or judgment. Clinical performance depends on several factors as noted below.

### Performance is Dependent on Underlying LLM Capabilities

The performance of agents hinges on the capabilities of their foundational language models, which can vary in terms of accuracy and reasoning power. These models are inherently prone to errors and hallucinations, making validation through human judgment essential.

### Performance is Dependent on Underlying Patient Data

System performance is dependent on the quality and completeness of data provided. Incomplete data may lead to incorrect, though seemingly reasonable, conclusions.

### Performance is Dependent on Tools Used by Agents

Certain agents utilize non-LLM based tools. The outcomes produced by these agents depend on the results provided by the underlying tools, as well as accurate tool usage and result interpretation. For example, the Radiology agent employs the CXRReportGen model to generate radiology reports. This model has specific limitations and performance characteristics that need to be considered.

### Limited Evaluation

Evaluation of individual agents, as well as the overall tumor board scenario, is limited and does not reflect the range of real-world scenarios that may be encountered. Although several agents are based on well-tested components, they may easily be applied to scenarios outside of their evaluation datasets. Other components are early prototypes and have not been evaluated for any application.

### PHI Considerations

The Healthcare Agent Orchestration framework is not meant for processing identifiable health records. Ensure that you follow all PHI/PII regulations when configuring or using the system.

## Performance Assessments and Evaluations

For detailed guidance on evaluating agent performance, running simulations, and measuring conversation quality, see the [Evaluation Guide](./evaluation.md) which provides comprehensive instructions for testing AI agents using synthetic conversations and modular evaluation metrics.

### Individual Agent Evaluations

When possible, the underlying agents have been based on evaluated technology to ensure a baseline performance under constrained conditions. While these do not imply performance at the scenario level, we reference the following validation of the individual agents:

**Radiology**

The Radiology agent employs Microsoft's Healthcare AI model [CXRReportGen](https://aka.ms/cxrreportgenmodelcard), which integrates multi-modal inputs—including current and prior images and report context—to generate grounded, interpretable radiology reports. The model has shown improved accuracy and transparency in automated chest X-ray interpretation, evaluated on both public and private data.

**PatientHistory and PatientStatus**

The PatientHistory and PatientStatus agents are based on the Universal Abstraction framework for medical data retrieval and structuring. This framework includes grounding to the original patient data for manual review and verification. This framework has been evaluated on identification and retrieval of a variety of oncology-specific data elements from clinical records.

**MedicalResearch**

The MedicalResearch agent is based on Microsoft's GraphRAG technology, ensuring that the responses are grounded in high-quality relevant research publications. This technology has been evaluated in a wide variety of domains and scenarios, outperforming traditional RAG or internal LLM knowledge in terms of comprehensiveness, human enfranchisement, and diversity.

**ClinicalTrials**

The ClinicalTrials agent is based on Scaling Clinical Trials Matching Using LLMs from Microsoft Research and Microsoft Health & Life Science, which demonstrates that LLMs can significantly improve the structuring of complex eligibility criteria and triage matching logic for oncology trials. Performance of this system is not guaranteed; however, the system has shown state-of-the-art performance compared to other implementations.

### Scenario Evaluations

Limited evaluations were made on a subset of patients that met the following inclusion criteria:

- Tumor board transcripts were available that contained patient case summaries comprising relevant health information to be considered by the tumor board in generating a recommendation.
- Complete EHR records were available, including all prior imaging, tested biomarkers, diagnosed conditions, demographics, medications, blood tests, physical exams, procedures, and social history.

In the case that a patient met the inclusion criteria, ground truth patient summaries were generated from the transcripts and used to measure performance. Specifically, patient case summaries were extracted from the tumor board transcripts using rule-based approaches, and converted to a standard template composed of a patient summary paragraph, followed by a timeline of relevant clinical events / diagnostics / treatments.

Performance measurements used to compare Healthcare Agent Orchestration to ground truth patient summaries leveraged the following metrics:

- **Lexical**: We use the collection of ROUGE metrics to assess similarities between text documents, as prior work has found these best correlate to human judgement among currently available lexical metrics [1].
- **Factual**: We developed a metric we term "TBFact", which is a modified form of RadFact [2]. At first text document is converted to a summarized list of facts using an LLM agent. Then a second agent is used to determine entailment of each fact from the second document.

System performance is not guaranteed. We recommend usage patterns matching that which was used for evaluation to maximize output quality.

## References

[1] Chen et al. "Fully Authentic Visual Question Answering Dataset from Online Communities" ECCV 2024. arxiv.org/pdf/2311.15562  
[2] Bannur et al. "MAIRA-2: Grounded Radiology Report Generation" https://arxiv.org/abs/2406.04449  
[3] Wong, C., Zhang, S., Gu, Y., Moung, C., Abel, J., Usuyama, N., Weerasinghe, R., Piening, B., Naumann, T., Bifulco, C. and Poon, H., 2023, December. Scaling clinical trial matching using large language models: a case study in oncology. In Machine Learning for Healthcare Conference (pp. 846-862). PMLR.
