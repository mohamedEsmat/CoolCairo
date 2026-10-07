using System;
using UnityEngine;

namespace CoolCairo
{
    // A figure from the analysis (docs/report/figures, the same images as the methodology report),
    // shown in the "Analysis maps" popup of the view it belongs to. Filled in by ProjectSetup.
    [Serializable]
    public class AnalysisFigure
    {
        public ViewMode view;
        public Texture2D image;
        public string title;
        [TextArea] public string caption;
    }
}
