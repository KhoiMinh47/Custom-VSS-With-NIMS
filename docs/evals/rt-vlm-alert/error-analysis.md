# Direct RT-VLM error analysis

Review direct results against the exact eight-second UTC chunk. Record one
feedback label and classify disagreement causes as sampling gap, occlusion,
reflection/screen confusion, image quality, prompt ambiguity or model
reasoning.

Do not infer ground truth from RT-CV detections: the direct path must remain
independent. RT-CV may be used only as a separately reported comparator after
operator labeling. At least 20 operator-reviewed chunks containing positive
and negative cases are required before reporting a provisional false-alert
rate; a larger balanced set is needed for business accuracy.
