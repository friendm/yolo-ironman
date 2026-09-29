from .models import Document


def extract_document(document_id):
    from .extraction import run_extraction

    document = Document.objects.select_related("document_type").filter(pk=document_id).first()
    if document is not None:
        run_extraction(document)
