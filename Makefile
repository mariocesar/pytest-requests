
default:
	pip install -r requirements.txt


publish: clean
	python setup.py sdist bdist_wheel
	twine upload dist/*

clean:
	rm -rf dist/
	rm -rf build/
