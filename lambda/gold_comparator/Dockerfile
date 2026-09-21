FROM public.ecr.aws/lambda/python:3.11

ENV TRANSFORMERS_CACHE=/var/task/hf_cache \
    HF_HOME=/var/task/hf_cache \
    TOKENIZERS_PARALLELISM=false \
    TRANSFORMERS_OFFLINE=1

RUN pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu

RUN pip install --no-cache-dir \
    numpy==1.26.4 \
    tokenizers==0.13.3 \
    transformers==4.33.3 \
    bert-score==0.3.13

RUN python -c "from bert_score import BERTScorer; BERTScorer(model_type='allenai/scibert_scivocab_uncased', num_layers=8, device='cpu')"

COPY handler.py ${LAMBDA_TASK_ROOT}/

CMD ["handler.lambda_handler"]
