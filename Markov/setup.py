from setuptools import setup, find_packages

setup(
    name='Markov',
    version='0.6',
    packages=find_packages(),
    py_modules=['Markov'],
    entry_points={
        'console_scripts': [
            'readCsv=Markov:read_csv_data',
            'getMatrix=Markov:get_matrix',
            'beamSearch=Markov:beam_search',
            'testHello=Markov:test_hello',
            'recIsolation=Markov:rec_txn_isolation',
            'checkIsolation=Markov:check_isolation'
        ]
    },
    install_requires=[

    ]
)