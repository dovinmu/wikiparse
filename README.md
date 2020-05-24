## installing
The trickiest thing is installing geopandas. You'll need GDAL + Fiona before that works, get those binaries [here](https://www.lfd.uci.edu/~gohlke/pythonlibs/#fiona) and [here](https://www.lfd.uci.edu/~gohlke/pythonlibs/#gdal). The order of operations for install is GDAL, Fiona, then geopandas.

Stuck on: running in iPython, I can import geopandas, but I can't import it in a jupyter notebook because importing shapely.geometry fails.
Here's a potentially similar error: https://github.com/conda-forge/shapely-feedstock/issues/55


Fiona @ file:///C:/Users/rowan/Downloads/Fiona-1.8.13-cp37-cp37m-win_amd64.whl
GDAL @ file:///C:/Users/rowan/Downloads/GDAL-3.0.4-cp37-cp37m-win_amd64.whl
geopandas @ file:///C:/Users/rowan/Downloads/geopandas-0.7.0-py3-none-any.whl
pandas==1.0.3
Shapely==1.7.0
