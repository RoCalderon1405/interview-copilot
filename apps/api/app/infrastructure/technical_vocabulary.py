"""Curated software/AI/data glossary for optional Nova-3 Keyterm Prompting.

The glossary is deliberately larger than the provider's per-connection budget.
Only a bounded, role-specific selection is sent over the cloud connection.
No interview transcripts or personal data enter this static catalog.
"""
from __future__ import annotations

from collections import defaultdict
from typing import Literal

VocabularyProfile = Literal[
    "general", "frontend", "backend", "fullstack", "ai-engineer",
    "data-analyst", "data-engineer", "cloud-devops", "security", "qa", "mobile",
]

# 500 is a *token* cap at Deepgram, not the number of keyterms. Use a small
# conservative, fixed subset: exact tokenizer behavior is provider-controlled.
MAX_ACTIVE_KEYTERMS = 48
MAX_ACTIVE_CHARACTERS = 650


def _terms(text: str) -> tuple[str, ...]:
    return tuple(line.strip() for line in text.splitlines() if line.strip())


COMMON = _terms("""
GraphQL
REST API
JWT
OAuth
FastAPI
Python
SQL
Docker
Kubernetes
AWS
Azure
CI/CD
RAG
TypeScript
""")

GLOSSARY: dict[str, tuple[str, ...]] = {
    "frontend": _terms("""
React
Angular
Next.js
Vue.js
Nuxt.js
Svelte
SvelteKit
JavaScript
TypeScript
HTML
CSS
SCSS
Tailwind CSS
Bootstrap
Vite
Webpack
Babel
ESLint
Prettier
Redux
Redux Toolkit
Zustand
React Query
TanStack Query
RxJS
NgRx
PrimeNG
Material UI
Storybook
Micro Frontends
Single Page Application
Server Side Rendering
Static Site Generation
Incremental Static Regeneration
React Server Components
Suspense
Hydration
Virtual DOM
DOM
Shadow DOM
Web Components
Custom Elements
WebSocket
GraphQL
REST API
tRPC
CORS
CSP
JWT
OAuth
OpenID Connect
Accessibility
WCAG
ARIA
Core Web Vitals
LCP
INP
CLS
Service Worker
Progressive Web App
PWA
IndexedDB
Web Workers
WebAssembly
E2E testing
Playwright
Cypress
Vitest
Jest
React Testing Library
Module Federation
BFF
Design System
Figma
Internationalization
Localization
Microfrontend
Server Actions
State Management
Lazy Loading
Tree Shaking
Code Splitting
WebRTC
Electron
"""),
    "backend": _terms("""
FastAPI
NestJS
ASP.NET Core
.NET Framework
Spring Boot
Express.js
Node.js
Django
Flask
Laravel
Ruby on Rails
Go
Gin
Fiber
Rust
Actix
Axum
Java
Kotlin
Python
C#
TypeScript
REST API
GraphQL
gRPC
Protocol Buffers
OpenAPI
Swagger
WebSocket
Webhooks
HTTP
HTTPS
HTTP/2
HTTP/3
JSON
XML
YAML
JWT
OAuth
OpenID Connect
Authentication
Authorization
RBAC
ABAC
ACL
Dependency Injection
Middleware
ORM
Entity Framework
Prisma
SQLAlchemy
Hibernate
Repository Pattern
Unit of Work
CQRS
Event Sourcing
DDD
Clean Architecture
Hexagonal Architecture
Microservices
Monolith
Modular Monolith
Message Queue
RabbitMQ
Kafka
Redis
Celery
Background Jobs
Idempotency
Rate Limiting
Circuit Breaker
Saga Pattern
Outbox Pattern
Transactions
ACID
BASE
Caching
Distributed Cache
Load Balancer
Reverse Proxy
Nginx
PostgreSQL
SQL Server
MongoDB
MySQL
DynamoDB
Elasticsearch
OpenSearch
Pagination
Keyset Pagination
Connection Pooling
Concurrency
AsyncIO
Multithreading
Memory Leak
Garbage Collection
Observability
OpenTelemetry
"""),
    "architecture": _terms("""
Clean Architecture
Hexagonal Architecture
Onion Architecture
Domain Driven Design
DDD
CQRS
Event Sourcing
SOLID
DRY
KISS
YAGNI
Separation of Concerns
Dependency Inversion
Design Patterns
Repository Pattern
Factory Pattern
Strategy Pattern
Observer Pattern
Adapter Pattern
Decorator Pattern
Builder Pattern
Singleton
Mediator Pattern
Command Pattern
Unit of Work
MVC
MVVM
MVP
Monolith
Modular Monolith
Microservices
Event Driven Architecture
Serverless Architecture
Service Oriented Architecture
SOA
API Gateway
Backend for Frontend
BFF
GraphQL Federation
Distributed Systems
CAP Theorem
PACELC
ACID
BASE
Eventual Consistency
Strong Consistency
Idempotency
Fault Tolerance
High Availability
Horizontal Scaling
Vertical Scaling
Load Balancing
Sharding
Partitioning
Replication
Caching
CQRS Read Model
Saga Pattern
Transactional Outbox
Circuit Breaker
Bulkhead Pattern
Retry Policy
Exponential Backoff
Architecture Decision Record
ADR
OpenSpec
Feature Flags
Blue Green Deployment
Canary Deployment
Twelve Factor App
"""),
    "cloud": _terms("""
AWS
Amazon Web Services
Azure
Microsoft Azure
Google Cloud
GCP
Cloud Computing
IaaS
PaaS
SaaS
FaaS
Serverless
AWS Lambda
Azure Functions
Cloud Functions
Amazon EC2
Azure Virtual Machines
Amazon S3
Azure Blob Storage
Google Cloud Storage
Amazon RDS
Amazon Aurora
Azure SQL
Cloud SQL
Amazon DynamoDB
Azure Cosmos DB
Amazon EKS
Azure AKS
Google GKE
Amazon ECS
AWS Fargate
Cloud Run
Azure Container Apps
AWS Step Functions
Azure Logic Apps
Amazon SQS
Amazon SNS
Amazon EventBridge
AWS Kinesis
Azure Service Bus
Azure Event Grid
Azure Event Hubs
AWS IAM
Microsoft Entra ID
Azure Key Vault
AWS KMS
AWS Secrets Manager
CloudWatch
Azure Monitor
Google Cloud Logging
CloudTrail
AWS CloudFormation
Terraform
Pulumi
Bicep
AWS CDK
VPC
Virtual Network
VNet
Subnet
Security Group
Network ACL
NAT Gateway
Internet Gateway
Load Balancer
Application Gateway
API Gateway
CloudFront
Azure CDN
Route 53
Azure DNS
Cloudflare
IAM Role
Managed Identity
Identity Federation
Multi Region
Availability Zone
Autoscaling
Disaster Recovery
RTO
RPO
Cloud Native
Cost Optimization
FinOps
Reserved Instances
Spot Instances
Well Architected Framework
Azure DevOps
GitHub Actions
"""),
    "devops": _terms("""
DevOps
DevSecOps
GitOps
CI/CD
Continuous Integration
Continuous Delivery
Continuous Deployment
Docker
Docker Compose
Kubernetes
K8s
Helm
Kustomize
Argo CD
Flux CD
Jenkins
GitHub Actions
GitLab CI
Azure Pipelines
Azure DevOps
CircleCI
Buildkite
Terraform
Pulumi
Ansible
Chef
Puppet
Vagrant
Infrastructure as Code
IaC
Linux
Bash
PowerShell
Git
GitHub
GitLab
Bitbucket
GitHub Desktop
Trunk Based Development
GitFlow
Pull Request
Code Review
Semantic Versioning
Conventional Commits
Monorepo
Nx
Turborepo
Dockerfile
OCI Image
Container Registry
Artifact Registry
Containerd
Ingress
Service Mesh
Istio
Linkerd
Prometheus
Grafana
Loki
Tempo
Jaeger
OpenTelemetry
Datadog
New Relic
Elastic Stack
ELK Stack
Sentry
Alertmanager
SLI
SLO
SLA
MTTR
MTBF
Blue Green Deployment
Canary Release
Feature Flag
Zero Downtime Deployment
Rollback
Disaster Recovery
Chaos Engineering
Load Testing
Performance Testing
GitHub Dependabot
Renovate
SonarQube
Trivy
Snyk
OWASP ZAP
"""),
    "security": _terms("""
OWASP
OWASP Top 10
OWASP ASVS
OWASP API Security
JWT
OAuth
OAuth 2.0
OpenID Connect
OIDC
SAML
SSO
MFA
2FA
Passkeys
WebAuthn
FIDO2
RBAC
ABAC
Zero Trust
Least Privilege
Identity and Access Management
IAM
Authentication
Authorization
Encryption
AES
RSA
ECC
TLS
HTTPS
mTLS
Public Key Infrastructure
PKI
Digital Signature
Hashing
SHA-256
HMAC
Argon2
bcrypt
PBKDF2
Password Salting
Key Rotation
Secret Management
SQL Injection
XSS
CSRF
SSRF
CORS
CSP
Clickjacking
Path Traversal
Command Injection
Prototype Pollution
Mass Assignment
IDOR
BOLA
Broken Access Control
Security Headers
Rate Limiting
Brute Force
Credential Stuffing
Session Fixation
Penetration Testing
Threat Modeling
STRIDE
DAST
SAST
SCA
SBOM
Supply Chain Security
Dependency Confusion
CVE
CVSS
NIST
CIS Benchmarks
SOC 2
ISO 27001
GDPR
PII
Data Masking
Secrets Scanning
Vulnerability Assessment
SIEM
SOC
DLP
EDR
WAF
Firewall
VPN
DNSSEC
"""),
    "ai": _terms("""
Artificial Intelligence
AI Engineer
Machine Learning
Deep Learning
Generative AI
GenAI
Large Language Model
LLM
Small Language Model
SLM
Transformer
Attention Mechanism
Self Attention
Multi Head Attention
Tokenization
Tokenizer
Context Window
Embedding
Embeddings
Vector Database
Vector Store
Semantic Search
Hybrid Search
Keyword Search
BM25
Cosine Similarity
Approximate Nearest Neighbor
ANN
HNSW
FAISS
Chroma
ChromaDB
Pinecone
Weaviate
Milvus
Qdrant
pgvector
Retrieval Augmented Generation
RAG
Agentic RAG
Graph RAG
Re-ranking
Cross Encoder
Chunking
Chunk Overlap
Grounding
Hallucination
Prompt Engineering
System Prompt
Few Shot Learning
Zero Shot Learning
Chain of Thought
Structured Outputs
Function Calling
Tool Calling
Model Context Protocol
MCP
Agent Framework
AI Agent
Multi Agent System
Agentic Workflow
OpenAI
Anthropic
Claude
GPT
Gemini
Llama
Mistral
Ollama
vLLM
LangChain
LangGraph
LlamaIndex
Hugging Face
Transformers Library
PyTorch
TensorFlow
Keras
Scikit-learn
XGBoost
LightGBM
Fine Tuning
LoRA
QLoRA
PEFT
Quantization
GGUF
ONNX
Inference
Batch Inference
Streaming Inference
Speech to Text
STT
Text to Speech
TTS
Deepgram
Whisper
Vosk
Voice Activity Detection
VAD
End of Speech
EOS
Natural Language Processing
NLP
Named Entity Recognition
NER
Computer Vision
CNN
OCR
Diffusion Model
Stable Diffusion
Reinforcement Learning
RLHF
DPO
Reward Model
Guardrails
Prompt Injection
LLM Evaluation
RAG Evaluation
Precision at K
Recall at K
MRR
NDCG
BLEU
ROUGE
BERTScore
MLOps
MLflow
Weights and Biases
Model Registry
Feature Store
Data Drift
Model Drift
Observability
Latency
Tokens per Second
TTFT
"""),
    "data": _terms("""
SQL
SQL Server
PostgreSQL
MySQL
Oracle Database
SQLite
MongoDB
Snowflake
BigQuery
Redshift
Databricks
Delta Lake
Apache Spark
PySpark
Apache Flink
Apache Beam
Apache Kafka
Apache Airflow
Dagster
Prefect
dbt
Data Warehouse
Data Lake
Data Lakehouse
Data Mart
Data Mesh
Data Fabric
ETL
ELT
CDC
Change Data Capture
Data Pipeline
Data Ingestion
Batch Processing
Stream Processing
Real Time Analytics
Data Orchestration
Data Modeling
Dimensional Modeling
Star Schema
Snowflake Schema
Fact Table
Dimension Table
Slowly Changing Dimension
SCD Type 2
Surrogate Key
Primary Key
Foreign Key
SQL Join
Window Functions
CTE
Common Table Expression
Stored Procedure
Database Index
Query Optimizer
Execution Plan
Partitioning
Sharding
Replication
Materialized View
Data Quality
Data Validation
Data Lineage
Data Catalog
Data Governance
Data Privacy
Data Profiling
Schema Evolution
Parquet
Avro
ORC
CSV
JSON
Apache Iceberg
Apache Hudi
Delta Sharing
Trino
Presto
DuckDB
Pandas
Polars
NumPy
DataFrame
Apache Hive
Hadoop
HDFS
Hive Metastore
DataOps
Reverse ETL
Data Contracts
Data Observability
"""),
    "analytics": _terms("""
Data Analyst
Business Analyst
Business Intelligence
BI
Power BI
Tableau
Looker
Looker Studio
Qlik Sense
Microsoft Excel
Google Sheets
Power Query
Power Pivot
DAX
M Language
SQL
SQL Server
Pivot Table
Tabla dinámica
Dashboard
KPI
Metrics
OKR
Drill Down
Slicer
Filter Context
Row Context
Measure
Calculated Column
Data Model
Star Schema
Fact Table
Dimension Table
Data Visualization
Data Storytelling
Descriptive Analytics
Diagnostic Analytics
Predictive Analytics
Prescriptive Analytics
Exploratory Data Analysis
EDA
Análisis exploratorio
Statistical Analysis
Descriptive Statistics
Inferential Statistics
Mean
Median
Mode
Standard Deviation
Variance
Percentile
Quantile
Correlation
Regression
Linear Regression
Logistic Regression
Hypothesis Testing
P-value
Confidence Interval
Statistical Significance
A/B Testing
Experiment Design
Cohort Analysis
Funnel Analysis
Retention Rate
Churn Rate
Customer Lifetime Value
CLV
LTV
CAC
Conversion Rate
ROAS
ROI
ARPU
Revenue Growth
Gross Margin
Forecasting
Time Series
Seasonality
Moving Average
Outliers
Missing Values
Normalization
Data Cleaning
Data Transformation
Data Wrangling
Pandas
NumPy
Matplotlib
Plotly
Seaborn
Jupyter Notebook
"""),
    "quality": _terms("""
Quality Assurance
QA
Quality Engineering
Test Automation
Unit Testing
Integration Testing
End to End Testing
E2E
Contract Testing
Consumer Driven Contracts
Pact
Regression Testing
Smoke Testing
Sanity Testing
Acceptance Testing
Behavior Driven Development
BDD
Test Driven Development
TDD
Gherkin
Cucumber
Selenium
Playwright
Cypress
Jest
Vitest
Pytest
JUnit
NUnit
XUnit
Mock
Stub
Test Double
Fixture
Test Coverage
Mutation Testing
Property Based Testing
Hypothesis
Load Testing
Stress Testing
Performance Testing
JMeter
K6
Locust
Postman
Newman
API Testing
REST Assured
OWASP ZAP
SAST
DAST
Static Analysis
SonarQube
Code Quality
Flaky Test
Test Pyramid
Continuous Testing
CI/CD
Release Candidate
Bug Triage
Defect Tracking
Root Cause Analysis
"""),
    "mobile": _terms("""
Android
iOS
Swift
SwiftUI
UIKit
Objective C
Kotlin
Jetpack Compose
Java
Flutter
Dart
React Native
Expo
Ionic
Capacitor
NativeScript
Mobile Development
Cross Platform
Native App
Hybrid App
Progressive Web App
App Store
Google Play
Xcode
Android Studio
Gradle
CocoaPods
Push Notifications
Firebase Cloud Messaging
FCM
APNs
Firebase
Firebase Authentication
Firestore
SQLite
Room Database
Core Data
Realm
Offline First
Deep Linking
Universal Links
App Links
Biometrics
Face ID
Touch ID
Crashlytics
Mobile Analytics
App Signing
Code Signing
Provisioning Profile
Accessibility
Performance Profiling
Battery Optimization
Background Tasks
Mobile CI/CD
Fastlane
"""),
    "computer_science": _terms("""
Algorithms
Data Structures
Time Complexity
Space Complexity
Big O Notation
Amortized Analysis
Array
Linked List
Stack
Queue
Deque
Hash Table
Hash Map
Set
Tuple
Heap
Priority Queue
Binary Tree
Binary Search Tree
AVL Tree
Red Black Tree
Trie
Graph
Directed Acyclic Graph
DAG
Adjacency List
Adjacency Matrix
Depth First Search
DFS
Breadth First Search
BFS
Dijkstra Algorithm
A Star Algorithm
Dynamic Programming
Memoization
Recursion
Backtracking
Divide and Conquer
Greedy Algorithm
Sorting Algorithms
Quicksort
Mergesort
Heapsort
Binary Search
Hashing
Hash Collision
Bloom Filter
LRU Cache
Garbage Collection
Memory Management
Stack Overflow
Heap Memory
Multithreading
Concurrency
Parallelism
Race Condition
Deadlock
Mutex
Semaphore
Lock Free
Asynchronous Programming
Event Loop
Future
Promise
Coroutine
Generator
Iterator
Functional Programming
Object Oriented Programming
OOP
Encapsulation
Inheritance
Polymorphism
Abstraction
SOLID
Dependency Injection
Interface Segregation
"""),
    "cloud_ai": _terms("""
Amazon Bedrock
Amazon SageMaker
Azure AI Foundry
Azure OpenAI Service
Azure Machine Learning
Google Vertex AI
Google Gemini API
AWS Glue
AWS Lake Formation
AWS Athena
AWS EMR
Amazon Redshift
Azure Data Factory
Azure Synapse Analytics
Microsoft Fabric
Microsoft Purview
Azure Databricks
Azure AI Search
Azure Cognitive Search
Azure Document Intelligence
Azure AI Speech
Google BigQuery
Google Dataflow
Google Pub/Sub
Google Dataproc
Cloud Composer
Google Cloud Storage
AWS Comprehend
AWS Textract
AWS Transcribe
AWS Polly
AWS Rekognition
Azure Event Hubs
Azure Stream Analytics
Azure Kubernetes Service
Amazon Elastic Kubernetes Service
Google Kubernetes Engine
MLflow
Kubeflow
KServe
BentoML
Ray Serve
Ray
Modal
RunPod
Hugging Face Inference Endpoints
Model Serving
GPU Inference
TensorRT
ONNX Runtime
Triton Inference Server
Prompt Caching
Semantic Caching
Vector Index
OpenSearch Vector Engine
Pinecone Serverless
Amazon Kendra
Vertex AI Vector Search
Embedding Model
Foundation Model
Inference Endpoint
Fine Tuning Job
Model Monitoring
AI Gateway
Observability
Data Residency
"""),
    "product": _terms("""
Agile
Scrum
Kanban
Sprint
Sprint Planning
Backlog
Product Owner
Scrum Master
User Story
Acceptance Criteria
Definition of Done
Story Points
Velocity
Burndown Chart
Retrospective
Product Management
Product Roadmap
Product Discovery
MVP
Minimum Viable Product
UX
UI
User Experience
User Interface
Design System
Wireframe
Prototype
User Research
Usability Testing
A/B Testing
Feature Flag
Customer Journey
User Persona
OKR
KPI
Stakeholder
Business Requirements
Functional Requirements
Nonfunctional Requirements
PRD
RFC
Architecture Decision Record
Technical Debt
Refactoring
Incident Management
Postmortem
Root Cause Analysis
SLA
SLO
SLI
"""),
    "bi_platforms": _terms("""
Power BI
Power BI Desktop
Power BI Service
Power BI Embedded
DAX
Power Query
Power Pivot
DAX Studio
Tabular Editor
Dataflows
Microsoft Fabric
OneLake
Semantic Model
Dataset
DirectQuery
Import Mode
Live Connection
Row Level Security
RLS
Column Level Security
Calculation Groups
Incremental Refresh
Composite Model
Relationship Cardinality
Filter Context
Row Context
CALCULATE
SUMX
RELATED
USERELATIONSHIP
TREATAS
ALLSELECTED
Time Intelligence
Date Dimension
Star Schema
Fact Table
Dimension Table
SSIS
SSAS
SSRS
Analysis Services
Reporting Services
Integration Services
Azure Synapse
Azure Data Factory
Tableau Prep
Tableau Server
LookML
Looker Studio
Qlik Sense
Excel Power Pivot
Pivot Table
Pivot Chart
VLOOKUP
XLOOKUP
INDEX MATCH
Power Automate
"""),
    "networks": _terms("""
TCP
UDP
IP
IPv4
IPv6
DNS
DHCP
HTTP
HTTPS
HTTP/2
HTTP/3
QUIC
TLS
SSL
TCP/IP
OSI Model
Subnet
CIDR
NAT
Firewall
WAF
VPN
Proxy
Reverse Proxy
Load Balancer
Ingress
Service Mesh
DNSSEC
CDN
WebSocket
WebRTC
WebTransport
gRPC
Protocol Buffers
MQTT
AMQP
SSH
SFTP
FTP
SMTP
IMAP
POP3
SNMP
ICMP
Ping
Traceroute
Packet Loss
Latency
Throughput
Bandwidth
Connection Pool
Keep Alive
Zero Trust
VPC
VNet
Private Endpoint
VPN Gateway
"""),
}

# Repeat priority categories to keep their high-value terms at the top while
# round-robin selection still includes cross-disciplinary concepts.
PROFILE_GROUPS: dict[str, tuple[str, ...]] = {
    "general": ("frontend", "backend", "ai", "analytics", "cloud", "data", "devops", "security", "architecture", "quality", "computer_science", "cloud_ai", "bi_platforms", "product"),
    "frontend": ("frontend", "frontend", "frontend", "architecture", "quality", "security"),
    "backend": ("backend", "backend", "backend", "architecture", "computer_science", "security", "data", "cloud"),
    "fullstack": ("frontend", "backend", "frontend", "backend", "architecture", "cloud", "data", "security"),
    "ai-engineer": ("ai", "ai", "ai", "cloud_ai", "data", "cloud", "backend", "analytics"),
    "data-analyst": ("analytics", "analytics", "analytics", "bi_platforms", "data", "ai", "cloud"),
    "data-engineer": ("data", "data", "data", "cloud_ai", "cloud", "devops", "analytics", "ai"),
    "cloud-devops": ("cloud", "devops", "cloud", "devops", "cloud_ai", "networks", "security", "architecture"),
    "security": ("security", "security", "security", "networks", "backend", "cloud"),
    "qa": ("quality", "quality", "quality", "frontend", "backend", "devops"),
    "mobile": ("mobile", "mobile", "mobile", "frontend", "backend", "cloud"),
}

SPANISH_HINTS = _terms("""
inteligencia artificial
aprendizaje automático
ciencia de datos
análisis de datos
análisis exploratorio
base de datos
seguridad informática
computación en la nube
""")


def keyterms_for(profile: str = "general", language: str = "en-US") -> tuple[str, ...]:
    """Select a small deterministic set with no external tokenizer dependency.

    A strict count/character bound limits the selected terms. Deepgram's
    500-token cap uses a provider tokenizer that is not available locally;
    token counts cannot be guaranteed from character counts alone. No
    arbitrary user keyterms are accepted.
    """
    if profile not in PROFILE_GROUPS:
        raise ValueError("unsupported_vocabulary_profile")
    if language not in {"en-US", "es-MX"}:
        raise ValueError("unsupported_vocabulary_language")

    selected: list[str] = []
    normalized: set[str] = set()
    total = 0

    def add(term: str) -> bool:
        nonlocal total
        key = term.casefold()
        if key in normalized:
            return True
        if len(selected) >= MAX_ACTIVE_KEYTERMS or total + len(term) > MAX_ACTIVE_CHARACTERS:
            return False
        selected.append(term)
        normalized.add(key)
        total += len(term)
        return True

    for term in COMMON:
        add(term)
    if language == "es-MX":
        for term in SPANISH_HINTS[:4]:
            add(term)

    indices: defaultdict[str, int] = defaultdict(int)
    categories = PROFILE_GROUPS[profile]
    while len(selected) < MAX_ACTIVE_KEYTERMS:
        added = False
        for category in categories:
            terms = GLOSSARY[category]
            index = indices[category]
            if index >= len(terms):
                continue
            term = terms[index]
            indices[category] += 1
            before = len(selected)
            add(term)
            added = added or len(selected) > before
            if len(selected) >= MAX_ACTIVE_KEYTERMS:
                break
        if not added:
            break
    return tuple(selected)
