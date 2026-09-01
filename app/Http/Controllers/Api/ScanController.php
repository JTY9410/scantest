<?php

namespace App\Http\Controllers\Api;

use App\Http\Controllers\Controller;
use Illuminate\Http\Request;
use App\Models\Scan;
use App\Traits\CrudOperations;
use App\Models\Activity;

class ScanController extends Controller
{
    use CrudOperations;

    protected $model = Scan::class;


    // TODO: 테스트 코드 scancontrollertest 재작성
    // TODO: app 컨테이너 스케쥴러 실행
        // 크론 계속 실패하니 부팅시 artisan schedule:run 도 방법


    /**
     * 스캔 목록 조회
     *
     * @LRDparam page integer|nullable 페이지 번호
     * @LRDparam per_page integer|nullable 페이지당 항목 수
     * @LRDparam search string|nullable 검색 조건
     * @LRDparam with string|nullable 포함할 관계
     * @LRDparam order string|nullable 정렬 조건
     * @LRDresponses 200|403|500
     *
     * @lrd:start
     * # 스캔 가능한 with 관계
     * - `user`: 스캔 소유자 정보
     * - `company`: 회사 정보
     * - `scanCodes`: 스캔 코드 정보
     *
     * # 조회 API 공통 기능
     *
     * ## 공통 파라미터 설명
     *
     * ### 1. 페이지네이션
     * - `page`: 페이지 번호 (기본값: 1)
     * - `per_page`: 페이지당 항목 수 (기본값: 15)
     *
     * ### 2. 검색 조건 (search)
     * `||`로 구분된 다중 조건을 지원합니다.
     *
     * #### 단순 검색
     * ```
     * field:value
     * ```
     * 예시: `type:ev` - 타입이 'ev'인 스캔만 조회
     *
     * #### 비교 검색
     * ```
     * field:operator:value
     * ```
     * - operator: =, >=, like, in 등
     * - like 검색시 자동으로 %value% 처리
     * - in 검색시 자동으로 (value1,value2,value3) 처리
     *
     * like 예시: `car_no:like:12가` - 차량번호에 '12가'가 포함된 스캔 조회
     * like 예시: `car_no:like:12가%,12나%` - 차량번호에 '12가' OR '12나'가 포함된 스캔 조회
     * in 예시: `car_no:in:abc,def,ghi` - 차량번호에 'abc', 'def', 'ghi' 중 하나가 포함된 스캔 조회
     *
     * ### 3. 정렬 조건 (order)
     * `||`로 구분된 다중 정렬을 지원합니다.
     * ```
     * field:direction
     * ```
     * - direction: asc(오름차순) 또는 desc(내림차순)
     *
     * 예시: `created_at:desc||car_no:asc` - 생성일 내림차순, 차량번호 오름차순 정렬
     *
     * ## 요청 예시
     * ```
     * GET /api/scans?page=1&per_page=10&search=type:ev||car_no:like:12가&with=user,company&order=created_at:desc||car_no:asc
     * ```
     *
     * 위 요청은:
     * - 1페이지의
     * - 페이지당 10개 항목을
     * - 타입이 'ev'이고 차량번호에 '12가'가 포함된
     * - 생성일 내림차순, 차량번호 오름차순으로 정렬된
     * - 소유자와 회사 정보를 포함한
     * 스캔 목록을 조회합니다.
     * @lrd:end
     */
    public function index(Request $request)
    {
        return $this->indexQuery($request, Scan::query());
    }

    /**
     * 스캔 생성
     *
     * @LRDparam type string|required 스캔 타입
     * @LRDparam device_type string|required 디바이스 타입
     * @LRDparam device_uid string|required 디바이스 고유번호
     * @LRDparam owner_id integer|nullable 소유자 ID
     * @LRDparam tester_id integer|required 테스터 ID
     * @LRDparam company_id integer|nullable 회사 ID
     * @LRDparam scan_vin string|nullable 스캔 VIN
     * @LRDparam car_no string|required 차량번호
     * @LRDparam car_vin string|required 차량 VIN
     * @LRDparam car_maker string|nullable 제조사
     * @LRDparam car_model string|required 차량 모델
     * @LRDparam car_submodel string|nullable 서브모델
     * @LRDparam car_cc integer|nullable 배기량
     * @LRDparam car_year integer|nullable 연식
     * @LRDparam car_fuel string|nullable 연료 종류
     * @LRDparam car_distance integer|nullable 주행거리 (km)
     * @LRDparam car_battery_capacity numeric|nullable 배터리 용량
     * @LRDparam car_discharge_energy numeric|nullable 방전 에너지
     * @LRDparam car_charge_energy numeric|nullable 충전 에너지
     * @LRDparam raw array|nullable 원본 데이터
     * @LRDparam bms_data string|nullable BMS 데이터(JSON)
     * @lrd:start
     * # raw
     * 고장 코드 JSON 배열
     *
     * 구조확인 테스트 후 scanCodes 로 적용 예정
     *
     * ex) [{"code": "123456",...}, {"code": "33333",...}]
     * @lrd:end
     * @LRDresponses 201|403|422|500
     */
    public function store(Request $request)
    {
        // TODO: raw -> scanCodes 로
        $validated = $request->validate([
            'type' => 'required|string',
            'device_type' => 'required|string',
            'device_uid' => 'required|string',
            'owner_id' => 'nullable|exists:users,id',
            'tester_id' => 'required|exists:users,id',
            'company_id' => 'nullable|exists:companies,id',
            'scan_vin' => 'nullable|string',
            'car_no' => 'required|string',
            'car_vin' => 'required|string',
            'car_maker' => 'nullable|string',
            'car_model' => 'required|string',
            'car_submodel' => 'nullable|string',
            'car_cc' => 'nullable|integer',
            'car_year' => 'nullable|integer',
            'car_fuel' => 'nullable|string',
            'car_distance' => 'nullable|integer',
            'car_battery_capacity' => 'nullable|numeric',
            'car_discharge_energy' => 'nullable|numeric',
            'car_charge_energy' => 'nullable|numeric',
            'raw' => 'nullable|array',
            'bms_data' => 'nullable|json',
        ]);

        if (isset($validated['bms_data'])) {
            $validated['bms_data'] = json_decode($validated['bms_data'], true);
        }

        return $this->storeQuery($validated, ['owner', 'tester', 'company', 'scanCodes']);
    }

    /**
     * 스캔 상세 조회
     *
     * @LRDparam search string|nullable 검색 조건
     * @LRDparam with string|nullable 포함할 관계
     * @LRDresponses 200|403|404|500
     *
     */
    public function show(Request $request, string $id)
    {
        return $this->showQuery($id, $request);
    }

    /**
     * 스캔 수정
     *
     * @LRDparam type string|sometimes|required 스캔 타입
     * @LRDparam device_type string|sometimes|required 디바이스 타입
     * @LRDparam device_uid string|sometimes|required 디바이스 고유번호
     * @LRDparam owner_id integer|sometimes|required 소유자 ID
     * @LRDparam tester_id integer|sometimes|required 테스터 ID
     * @LRDparam company_id integer|sometimes|required 회사 ID
     * @LRDparam scan_vin string|sometimes|required 스캔 VIN
     * @LRDparam car_no string|sometimes|required 차량번호
     * @LRDparam car_vin string|sometimes|required 차량 VIN
     * @LRDparam car_maker string|nullable 제조사
     * @LRDparam car_model string|sometimes|required 차량 모델
     * @LRDparam car_submodel string|nullable 서브모델
     * @LRDparam car_cc integer|nullable 배기량
     * @LRDparam car_year integer|nullable 연식
     * @LRDparam car_fuel string|nullable 연료 종류
     * @LRDparam car_distance integer|nullable 주행거리 (km)
     * @LRDparam car_battery_capacity numeric|nullable 배터리 용량
     * @LRDparam car_discharge_energy numeric|nullable 방전 에너지
     * @LRDparam car_charge_energy numeric|nullable 충전 에너지
     * @LRDparam raw array|nullable 원본 데이터
     * @LRDparam bms_data string|nullable BMS 데이터(JSON)
     * @LRDresponses 200|403|404|422|500
     */
    public function update(Request $request, string $id)
    {
        $validated = $request->validate([
            'type' => 'sometimes|required|string',
            'device_type' => 'sometimes|required|string',
            'device_uid' => 'sometimes|required|string',
            'owner_id' => 'sometimes|required|exists:users,id',
            'tester_id' => 'sometimes|required|exists:users,id',
            'company_id' => 'sometimes|required|exists:companies,id',
            'scan_vin' => 'sometimes|required|string',
            'car_no' => 'sometimes|required|string',
            'car_vin' => 'sometimes|required|string',
            'car_maker' => 'nullable|string',
            'car_model' => 'sometimes|required|string',
            'car_submodel' => 'nullable|string',
            'car_cc' => 'nullable|integer',
            'car_year' => 'nullable|integer',
            'car_fuel' => 'nullable|string',
            'car_distance' => 'nullable|integer',
            'car_battery_capacity' => 'nullable|numeric',
            'car_discharge_energy' => 'nullable|numeric',
            'car_charge_energy' => 'nullable|numeric',
            'raw' => 'nullable|array',
            'bms_data' => 'nullable|json',
        ]);

        if (isset($validated['bms_data'])) {
            $validated['bms_data'] = json_decode($validated['bms_data'], true);
        }

        return $this->updateQuery($id, $validated, ['owner', 'tester', 'company', 'scanCodes']);
    }

    /**
     * 스캔 삭제
     *
     * @LRDresponses 200|403|404|500
     */
    public function destroy(string $id)
    {
        return $this->destroyQuery($id);
    }

    /**
     * 스캔 결과를 이메일로 전송
     *
     * @LRDparam email string|required 수신자 이메일
     * @LRDresponses 200|403|404|422|500
     * @lrd:start
     * # 미개발
     * @lrd:end
     */
    public function sendEmail(Request $request, string $id)
    {
        $validated = $request->validate([
            'email' => 'required|email',
        ]);

        $scan = $this->model::with(['owner', 'tester', 'company', 'scanCodes'])
            ->findOrFail($id);

        // TODO: 이메일 전송 로직 구현
        // Mail::to($validated['email'])->send(new ScanResultMail($scan, $validated));

        return response()->json([
            'message' => '이메일이 성공적으로 전송되었습니다. [테스트!]',
            'scan_id' => $id
        ]);
    }

    /**
     * 스캔 결과 PDF 생성
     *
     * @LRDresponses 200|403|404|500
     * @lrd:start
     * # 미개발
     * @lrd:end
     */
    public function generatePdf(string $id)
    {
        $scan = $this->model::with(['owner', 'tester', 'company', 'scanCodes'])
            ->findOrFail($id);

        // TODO: PDF 생성 로직 구현
        // $pdf = PDF::loadView('pdfs.scan-result', ['scan' => $scan]);
        // return $pdf->download('scan-result-' . $id . '.pdf');

        return response()->json([
            'message' => 'PDF가 성공적으로 생성되었습니다. [테스트!]',
            'scan_id' => $id
        ]);
    }


    /**
     * 차량정보 조회
     * @LRDparam car_no string|required
     * @LRDresponses 200|400
     */
    public function getCarInfo(Request $request)
    {
        $car_no = $request->input('car_no');

        if( !$car_no ) {
            return response()->json([
                'message' => '차량번호를 입력해주세요.'
            ], 400);
        }

        // ?reload=true // 강제 새로고침

        $authkey = 'wecarscan_betatest';
        $url = 'https://diag-dev.wecarmobility.co.kr/api/get_car_info';
        $data = [
            'authkey' => $authkey,
            'car_no' => $car_no
        ];
        $response = \Http::asForm()->post($url, $data);
        $response = $response->json();

        if( auth()->check() ) {
            Activity::log(
                auth()->user(),
                'Scan: Get Car Info',
                ['response' => $response, 'request' => $data]
            );
        }

        // return response()->json([
        //     'message' => $response['msg'],
        //     'response' => $response
        // ], 400);
        if( $response['status'] != 'ok' ) {
            return response()->json([
                'message' => $response['msg'],
                'response' => $response
            ], 400);
        }

        return response()->json(['data' => $response['dto']]);
    }

}
