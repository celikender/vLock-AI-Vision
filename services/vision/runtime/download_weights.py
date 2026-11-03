"""Download official gated weights after the user has signed in and been approved."""
from huggingface_hub import hf_hub_download

if __name__ == '__main__':
    path = hf_hub_download('facebook/sam3.1', 'sam3.1_multiplex.pt')
    print('SAM 3.1 checkpoint is ready in the local model cache.')