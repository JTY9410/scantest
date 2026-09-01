<?php

namespace App\Http\Controllers\Api;

use App\Http\Controllers\Controller;
use Illuminate\Http\Request;
use App\Models\CarMismatchReport;
use App\Traits\CrudOperations;

class CarMismatchReportController extends Controller
{
    use CrudOperations;

    protected $model = CarMismatchReport::class;

    /**
     * 차량 정보 불일치 신고 목록 조회
     * @LRDparam car_no string|nullable 차량번호
     * @LRDparam api_vin string|nullable 조회차대번호
     * @LRDparam scan_vin string|nullable 스캔차대번호
     * @LRDparam per_page integer|nullable 페이지당 항목 수 (기본값: 15)
     * @LRDresponses 200
     */
    public function index(Request $request)
    {
        return $this->indexQuery($request, CarMismatchReport::query());
    }

    /**
     * 차량 정보 불일치 신고 생성
     * @LRDparam car_no string|required 차량번호
     * @LRDparam api_vin string|required 조회차대번호
     * @LRDparam scan_vin string|required 스캔차대번호
     * @LRDresponses 201|422
     */
    public function store(Request $request)
    {
        $validated = $request->validate([
            'car_no' => 'required|string|max:20',
            'api_vin' => 'required|string|max:17',
            'scan_vin' => 'required|string|max:17',
        ]);

        return $this->storeQuery($validated, ['user']);
    }

    /**
     * 차량 정보 불일치 신고 상세 조회
     * @LRDparam search string|nullable 검색 조건
     * @LRDresponses 200|404
     */
    public function show(Request $request, string $id)
    {
        return $this->showQuery($id, $request);
    }

    /**
     * 차량 정보 불일치 신고 수정
     * @LRDparam id integer|required 신고 아이디
     * @LRDparam car_no string|required 차량번호
     * @LRDparam api_vin string|required 조회차대번호
     * @LRDparam scan_vin string|required 스캔차대번호
     * @LRDresponses 200|404|422
     */
    public function update(Request $request, string $id)
    {
        $validated = $request->validate([
            'car_no' => 'required|string|max:20',
            'api_vin' => 'required|string|max:17',
            'scan_vin' => 'required|string|max:17',
        ]);

        return $this->updateQuery($id, $validated, ['user']);
    }

    /**
     * 차량 정보 불일치 신고 삭제
     * @LRDparam id integer|required 신고 아이디
     * @LRDresponses 200|404
     */
    public function destroy(string $id)
    {
        return $this->destroyQuery($id);
    }
}
