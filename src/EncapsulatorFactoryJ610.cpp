// Model-specific factory for the HP DeskJet 3050 J610.
// The model's upstream PPD requests pcl3gui2. All raster encoding stays in HP's
// unmodified Pcl3Gui2, Mode9, Mode10 and ErnieFilter implementations.
#include "EncapsulatorFactory.h"
#include "Pcl3Gui2.h"
#include <cstring>

Encapsulator *EncapsulatorFactory::GetEncapsulator(char *technology)
{
    if (technology && std::strcmp(technology, "pcl3gui2") == 0)
        return new Pcl3Gui2();
    return NULL;
}
