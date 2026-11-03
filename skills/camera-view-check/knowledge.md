- An empty SAM result looks the same as a blocked or dark camera. This check answers in
  VlmState so SCADA can treat "not usable" as Unknown for the zone.
- The rule template is a person-in-area rule; replace the object for other scenarios.
- Every check sends one frame to Meta; 300 s keeps cost and traffic low.
